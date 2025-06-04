import os
import io
import asyncio
import logging  # Import standard logging
from typing import List
from contextlib import asynccontextmanager

from PIL import Image
import torch
from transformers import ViTImageProcessor, ViTModel
from surrealdb import AsyncSurreal, AsyncWsSurrealConnection, AsyncHttpSurrealConnection

# --- Configuration ---
SURREAL_URI = os.environ["SURREAL_URI"]
SURREAL_USER = os.environ["SURREAL_USER"]
SURREAL_PASS = os.environ["SURREAL_PASS"]
SURREAL_NAMESPACE = "partyscene"
SURREAL_DATABASE = "partyscene"
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
db_connection: AsyncWsSurrealConnection | AsyncHttpSurrealConnection | None = None
processor: ViTImageProcessor | None = None
model: ViTModel | None = None
device: torch.device | None = None
# Locks to ensure thread-safe operations
model_lock = asyncio.Lock()
db_init_lock = asyncio.Lock()  # Shared lock for database initialization
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
        async with db_init_lock:
            await db_connection.signin(
                {"username": SURREAL_USER, "password": SURREAL_PASS}
            )
            await db_connection.use(SURREAL_NAMESPACE, SURREAL_DATABASE)
            await db_connection.query(
                "INFO FOR DB;"
            )  # Check if the connection is established
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

import obstore as obs

class Job:
    """
    Manages RabbitMQ connection, message decoding, database interactions,
    and coordination of message processing logic.
    """

    def __init__(self, *args, **kwargs):
        self.OBS_STORE = obs.store.GCSStore(os.environ.get("GCS_BUCKET_NAME", "partyscene"))
        ...
        
    async def start(self):
        await init_globals()

    async def stop(self):
        await close_globals()

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
    
    async def fetch_media_objects(self):
        try:
            async with model_lock:
                async with self.db_session() as db:
                    result = await db.query(
                        "SELECT filename FROM media WHERE status = 'pending'",
                    )
            logger.debug(
                f"Successfully fetched {len(result)} media objects"
            )  # Use debug for success logs
            return result
        except Exception as e:
            logger.error(f"SurrealDB fetch failed for media objects", exc_info=True)
            raise  # Re-raise to allow retry/DLQ
    
    async def process(self):
        media_objects = await self.fetch_media_objects()
        for object in media_objects:
            filename = object['filename']
            logger.debug(f"Processing media for file '{filename}'")
            obs_result = await obs.get_async(self.OBS_STORE, filename)
            embeddings = await extract_embeddings(bytes(await obs_result.bytes_async()))
            await self.save(filename, embeddings)

# --- Instantiate the Worker ---
worker = Job()

if __name__ == "__main__":
    import asyncio

    async def main():
        try:
            await worker.start()
            await worker.process()  # Example usage of the worker instance
        finally:
            await worker.stop()

    asyncio.run(main())
# ----------------------------