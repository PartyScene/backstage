import os
import io
import asyncio
import ormsgpack
import logging  # Import standard logging
from typing import List
from contextlib import asynccontextmanager

from PIL import Image
import torch
from transformers import ViTImageProcessor, ViTModel
from faststream import FastStream
from faststream.rabbit import RabbitBroker, RabbitQueue, RabbitMessage
from surrealdb import AsyncSurreal, AsyncWsSurrealConnection

# --- Configuration ---
RABBITMQ_URI = os.environ["RABBITMQ_URI"]
SURREAL_URI = os.environ["SURREAL_URI"]
SURREAL_USER = os.environ["SURREAL_USER"]
SURREAL_PASS = os.environ["SURREAL_PASS"]
SURREAL_NAMESPACE = "partyscene"
SURREAL_DATABASE = "partyscene"
RABBITMQ_R18E_QUEUE_NAME = "R18E"
VIT_MODEL_NAME = "google/vit-base-patch16-224-in21k"
MAX_RETRIES = 3
RETRY_DELAY = 2  # Base delay for exponential backoff
EMBEDDING_DIM = 768  # Expected dimension for ViT-Base

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)  # Get logger for this module
# ---------------------


# --- Global Variables ---
db_connection: AsyncWsSurrealConnection | None = None
processor: ViTImageProcessor | None = None
model: ViTModel | None = None
device: torch.device | None = None
# Lock to ensure thread-safe model inference, critical for GPUs
model_lock = asyncio.Lock()
# ----------------------


async def extract_embeddings(image_bytes: bytes) -> List[float]:
    """
    Loads image from bytes, extracts embeddings using the global ViT model.

    Args:
        image_bytes: Raw bytes of the image file.

    Returns:
        A list of floats representing the image embedding.

    Raises:
        ValueError: If image bytes are invalid.
        RuntimeError: If model resources are not initialized or inference fails.
    """
    # global processor, model, device, model_lock
    if not processor or not model or not device:
        # Log critical failure if resources aren't ready
        logger.critical("Model resources not initialized during embedding extraction.")
        raise RuntimeError("Model resources not initialized.")

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as img_err:
        logger.error("Failed to load image from provided bytes", exc_info=True)
        raise ValueError("Invalid image bytes provided") from img_err

    inputs = processor(images=image, return_tensors="pt").to(device)

    async with model_lock:
        try:
            with torch.no_grad():
                outputs = model(**inputs)
                cls_embedding = outputs.last_hidden_state[:, 0, :]
        except Exception as model_err:
            logger.error("Model inference failed", exc_info=True)
            raise RuntimeError("Model inference failed") from model_err

    embedding_list = cls_embedding.squeeze().cpu().tolist()

    if len(embedding_list) != EMBEDDING_DIM:
        # Log a warning if dimensions don't match, allows investigation
        logger.warning(
            f"Extracted embedding dimension ({len(embedding_list)}) does not match expected ({EMBEDDING_DIM})."
        )

    return embedding_list


async def init_globals():
    """Initialize global variables (model, db connection) during app startup."""
    global processor, model, device, db_connection, EMBEDDING_DIM
    logger.info("Initializing global resources...")
    processor = ViTImageProcessor.from_pretrained(VIT_MODEL_NAME)
    model = ViTModel.from_pretrained(VIT_MODEL_NAME, output_hidden_states=False)

    actual_dim = model.config.hidden_size
    if actual_dim != EMBEDDING_DIM:
        logger.warning(
            f"Model config hidden size ({actual_dim}) differs from EMBEDDING_DIM ({EMBEDDING_DIM}). Using {actual_dim}."
        )
        EMBEDDING_DIM = actual_dim
    else:
        logger.info(f"Confirmed model embedding dimension: {EMBEDDING_DIM}")

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()  # Set to evaluation mode
    logger.info(f"Model loaded on device: {device}")

    db_connection = AsyncSurreal(SURREAL_URI)
    try:
        await db_connection.signin({"username": SURREAL_USER, "password": SURREAL_PASS})
        await db_connection.use(SURREAL_NAMESPACE, SURREAL_DATABASE)
        logger.info("Database connection established.")
    except Exception as e:
        # Log as critical because the app likely cannot function without DB
        logger.critical("Database initialization failed!", exc_info=True)
        db_connection = None
        raise  # Prevent app startup


async def close_globals():
    """Close global connections (db) during app shutdown."""
    global db_connection
    if db_connection:
        logger.info("Closing database connection...")
        try:
            await db_connection.close()
        except Exception:
            logger.exception("Error closing database connection.")
        finally:
            db_connection = None
    logger.info("Global resources closed.")


class Job(RabbitBroker):
    """
    Manages RabbitMQ connection, message decoding, database interactions,
    and coordination of message processing logic.
    """

    def __init__(self, *args, **kwargs):
        self.RABBITMQ_R18E_QUEUE = RabbitQueue(
            RABBITMQ_R18E_QUEUE_NAME, auto_delete=False, durable=False
        )
        super().__init__(
            url=RABBITMQ_URI, decoder=self.decode_message_body, *args, **kwargs
        )

    async def start(self):
        await super().start()
        await init_globals()

    async def stop(self):
        await close_globals()
        await super().stop()

    @asynccontextmanager
    async def db_session(self):
        """Provides a managed database session."""
        # global db_connection
        if not db_connection:
            logger.error(
                "Attempted to use DB session, but connection is not available."
            )
            raise ConnectionError("Database connection is not available.")
        try:
            yield db_connection
        except Exception as e:
            logger.exception("Database session error occurred.")
            raise

    async def save(self, filename: str, embeddings: list):
        """Saves embeddings and updates status in SurrealDB."""
        if not filename:
            logger.error("Attempted to save embeddings with an empty filename.")
            raise ValueError("Filename cannot be empty for saving.")
        if len(embeddings) != EMBEDDING_DIM:
            logger.error(
                f"Attempting to save embedding with incorrect dimension ({len(embeddings)} vs {EMBEDDING_DIM}) for {filename}"
            )
            raise ValueError(f"Embedding dimension mismatch for {filename}")
        try:
            async with model_lock:
                async with self.db_session() as db:
                    await db.query(
                        "UPDATE media SET embeddings = $embeddings, status = 'completed' WHERE filename = $filename",
                        {"filename": filename, "embeddings": embeddings},
                    )
            logger.debug(
                f"Successfully saved embeddings for {filename}"
            )  # Use debug for success logs
        except Exception as e:
            logger.error(f"SurrealDB save failed for {filename}", exc_info=True)
            raise  # Re-raise to allow retry/DLQ

    async def decode_message_body(self, msg: RabbitMessage, original_decoder):
        """Custom decoder: Assumes body is ormsgpack-encoded bytes."""
        if msg.decoded_body is not None:
            return msg
        if not isinstance(msg.body, bytes):
            return msg
        try:
            msg.body = ormsgpack.unpackb(
                msg.body
            )  # Decodes raw bytes into Python object (likely bytes again in this case)
            msg.decoded_body = True
            return msg
        except ValueError as e:
            logger.error("Ormsgpack decoding failed. Invalid format.", exc_info=True)
            raise ValueError("Invalid ormsgpack body") from e
        except Exception as e:
            logger.exception(
                "Unexpected decoding error."
            )  # Use exception to include traceback
            try:
                return await original_decoder(msg)
            except Exception as e:
                return msg

    async def process_r18e_event(
        self, event_type: str, filename: str, image_bytes: bytes
    ):
        """Routes event processing based on type."""
        logger.debug(f"Processing event type '{event_type}' for file '{filename}'")
        if event_type == "MEDIA":
            embeddings = await extract_embeddings(image_bytes)
            await self.save(filename, embeddings)
        else:
            logger.warning(
                f"Received unknown event type '{event_type}' for file '{filename}'"
            )
            # Depending on requirements, might raise ValueError or just log and ACK
            raise ValueError(f"Unknown event type encountered in headers: {event_type}")

    async def _handle_retry(
        self,
        image_bytes: bytes,
        headers: dict,
        message: RabbitMessage,
        retry_count: int,
    ):
        """Manages the retry logic for failed message processing."""
        message_id = message.message_id or "UNKNOWN"
        if retry_count < MAX_RETRIES:
            retry_count += 1
            headers["retry_count"] = retry_count  # Update header for next attempt
            delay = RETRY_DELAY**retry_count
            logger.info(
                f"Retrying message {message_id} (attempt {retry_count}/{MAX_RETRIES}) in {delay} seconds..."
            )
            await asyncio.sleep(delay)
            try:
                await self.requeue_message(image_bytes, headers)
                await message.ack()  # ACK original *after* successful requeue
                logger.info(f"Message {message_id} successfully requeued for retry.")
            except Exception as requeue_err:
                logger.error(f"Failed to requeue message {message_id}", exc_info=True)
                # If requeue fails, NACK without requeue to avoid infinite loops
                await message.nack(requeue=False)
        else:
            logger.error(
                f"Max retries ({MAX_RETRIES}) reached for message {message_id}. Giving up."
            )
            # Implement DLQ (Dead Letter Queue) logic here if desired
            # e.g., await self.publish(ormsgpack.packb(image_bytes), queue="my_dlq", headers=headers)
            # ACK the message to remove it from the main queue, even if DLQ fails
            await message.ack()

    async def requeue_message(self, image_bytes: bytes, headers: dict):
        """Re-encodes body with msgpack and republishes the message."""
        try:
            body_to_publish = ormsgpack.packb(image_bytes)
        except Exception as e:
            logger.error(
                f"Ormsgpack encoding failed during requeue attempt.: {e}", exc_info=True
            )
            raise  # Propagate error to _handle_retry

        # Access queue via self.RABBITMQ_R18E_QUEUE
        await self.publish(
            body_to_publish,
            queue=self.RABBITMQ_R18E_QUEUE.name,
            routing_key=self.RABBITMQ_R18E_QUEUE.routing_key
            or self.RABBITMQ_R18E_QUEUE.name,
            headers=headers,
        )


# --- Instantiate the Broker ---
broker = Job()
# ----------------------------


# --- Subscriber Handler (Outside Class) ---
@broker.subscriber(broker.RABBITMQ_R18E_QUEUE)
async def handle_r18e(message):
    """
    Main message handler: extracts metadata, routes processing, handles errors/retries.
    """
    headers = message.headers
    body = message.body

    event_type = headers.get("type")
    filename = headers.get("filename")
    message_id = (
        message.message_id or f"amqp_{message.delivery_tag}"
    )  # Use delivery tag if no message_id
    retry_count = headers.get("retry_count", 0)

    # Basic header validation
    if not event_type or not filename:
        logger.error(
            f"Missing 'type' or 'filename' header(s) for message {message_id}. Headers: {headers}"
        )
        # NACK without requeue for fundamentally invalid messages
        await message.nack(requeue=False)
        return  # Stop processing this message

    logger.info(
        f"Received message {message_id} for file '{filename}' (Type: {event_type}, Retry: {retry_count})"
    )

    try:
        # Delegate processing to the broker instance's method
        await broker.process_r18e_event(event_type, filename, body)
        logger.info(
            f"Successfully processed message {message_id} for file '{filename}'"
        )
        # Automatic ACK happens on successful completion if auto_ack=True (default)

    except (ConnectionError, TimeoutError, asyncio.TimeoutError) as transient_error:
        # Errors that might resolve themselves on retry
        logger.warning(
            f"Transient error processing message {message_id} (Retry {retry_count}): {transient_error}"
        )
        await broker._handle_retry(body, headers, message, retry_count)
    except ValueError as data_error:
        # Errors indicating bad data (invalid image, unknown type, missing headers handled above)
        logger.error(
            f"Data error processing message {message_id}: {data_error}. Won't retry."
        )
        # Let FastStream NACK without requeue by raising, or explicitly NACK here
        await message.nack(requeue=False)
    except RuntimeError as runtime_err:
        # Errors during ML inference or other critical runtime issues
        logger.error(
            f"Runtime error processing message {message_id} (Retry {retry_count}): {runtime_err}",
            exc_info=True,
        )
        await broker._handle_retry(
            body, headers, message, retry_count
        )  # Retry runtime errors
    except Exception as e:
        # Catch-all for truly unexpected errors
        logger.exception(
            f"Unexpected error processing message {message_id} (Retry {retry_count}): {e}"
        )  # Use exception for traceback
        await broker._handle_retry(body, headers, message, retry_count)


# ----------------------------------------


# Create the FastStream application instance
app = FastStream(broker)
