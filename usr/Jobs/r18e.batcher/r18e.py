import os
import io
import asyncio
import logging  # Import standard logging
from typing import List, Dict
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
# Pin to specific revision for security (prevent supply chain attacks)
VIT_MODEL_REVISION = "5dca96d486dc2a9590c20b1c4b5c2b6c8b8e7e6a"
MAX_RETRIES = 3
RETRY_DELAY = 2  # Base delay for exponential backoff
EMBEDDING_DIM = 768  # Expected dimension for ViT-Base

# Optimization parameters
BATCH_SIZE = 32  # Process images in batches for better performance
MAX_CONCURRENT_DOWNLOADS = 10  # Parallel GCS downloads
USE_FP16 = True  # Half precision for 2x speedup on GPU
USE_TORCH_COMPILE = True  # PyTorch 2.0+ graph compilation (20-40% faster)
USE_BETTER_TRANSFORMER = True  # Optimum BetterTransformer (if available)

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


async def extract_embeddings_batch(image_bytes_list: List[bytes]) -> List[List[float]]:
    """
    Extract embeddings for a batch of images (optimized for performance).

    Args:
        image_bytes_list: List of raw image bytes.

    Returns:
        List of embedding vectors (one per image).

    Raises:
        RuntimeError: If model resources are not initialized or inference fails.
    """
    if not processor or not model or not device:
        logger.critical("Model resources not initialized during embedding extraction.")
        raise RuntimeError("Model resources not initialized.")

    # Load and validate all images
    images = []
    valid_indices = []
    for idx, img_bytes in enumerate(image_bytes_list):
        try:
            image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            images.append(image)
            valid_indices.append(idx)
        except Exception as e:
            logger.error(f"Failed to load image at batch index {idx}: {e}")

    if not images:
        logger.warning("No valid images in batch")
        return []

    # Batch preprocessing
    inputs = processor(images=images, return_tensors="pt")
    
    # Move to device with proper dtype handling for FP16
    if device.type == "cuda" and USE_FP16:
        inputs = {k: v.to(device).half() if v.dtype == torch.float32 else v.to(device) 
                 for k, v in inputs.items()}
    else:
        inputs = {k: v.to(device) for k, v in inputs.items()}

    # Single inference call for entire batch (MUCH faster)
    async with model_lock:
        try:
            with torch.no_grad():
                outputs = model(**inputs)
                cls_embeddings = outputs.last_hidden_state[:, 0, :]
        except Exception as e:
            logger.error("Batch model inference failed", exc_info=True)
            raise RuntimeError("Batch inference failed") from e

    # Convert to list of embeddings (ensure float32 for consistency)
    embeddings_list = cls_embeddings.float().cpu().tolist()

    return embeddings_list


async def extract_embeddings(image_bytes: bytes) -> List[float]:
    """
    Single image wrapper (for backwards compatibility).
    For better performance, use extract_embeddings_batch().
    """
    result = await extract_embeddings_batch([image_bytes])
    return result[0] if result else []


async def init_globals():
    """Initialize global variables with maximum optimization."""
    global processor, model, device, db_connection, EMBEDDING_DIM
    logger.info("Initializing optimized global resources...")
    
    # Determine device early
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    use_gpu = device.type == "cuda"
    logger.info(f"Target device: {device}")
    
    # Load processor (lightweight, no optimization needed)
    processor = ViTImageProcessor.from_pretrained(
        VIT_MODEL_NAME, 
        revision=VIT_MODEL_REVISION
    )
    logger.info("Processor loaded")
    
    # Optimized model loading
    load_kwargs = {
        "revision": VIT_MODEL_REVISION,
        "output_hidden_states": False,
        "low_cpu_mem_usage": True,  # Reduces memory during loading
    }
    
    # GPU-specific optimizations
    if use_gpu and USE_FP16:
        load_kwargs["torch_dtype"] = torch.float16  # Load directly in FP16
        logger.info("Loading model in FP16 precision")
    
    model = ViTModel.from_pretrained(VIT_MODEL_NAME, **load_kwargs)
    
    # Verify embedding dimension
    actual_dim = model.config.hidden_size
    if actual_dim != EMBEDDING_DIM:
        logger.warning(f"Updating EMBEDDING_DIM from {EMBEDDING_DIM} to {actual_dim}")
        EMBEDDING_DIM = actual_dim
    
    # Move to device if not already there
    if not use_gpu or not USE_FP16:
        model.to(device)
        if use_gpu and USE_FP16:
            model = model.half()
    
    model.eval()  # Evaluation mode
    
    # PyTorch 2.0+ optimization: torch.compile
    if USE_TORCH_COMPILE and hasattr(torch, "compile"):
        try:
            logger.info("Compiling model with torch.compile()...")
            model = torch.compile(
                model, 
                mode="reduce-overhead",  # Best for batch inference
                fullgraph=False  # More compatible
            )
            logger.info("Model compiled successfully")
        except Exception as e:
            logger.warning(f"torch.compile failed, continuing without: {e}")
    
    # BetterTransformer optimization (if available)
    if USE_BETTER_TRANSFORMER:
        try:
            from optimum.bettertransformer import BetterTransformer
            logger.info("Applying BetterTransformer optimization...")
            model = BetterTransformer.transform(model)
            logger.info("BetterTransformer applied")
        except ImportError:
            logger.debug("optimum not available, skipping BetterTransformer (pip install optimum)")
        except Exception as e:
            logger.warning(f"BetterTransformer failed: {e}")
    
    # Enable torch inference mode globally for this model
    torch.set_grad_enabled(False)
    
    # Warmup inference (compile optimization, cache initialization)
    logger.info("Running warmup inference (3 passes)...")
    dummy_image = Image.new("RGB", (224, 224))
    dummy_inputs = processor(images=[dummy_image], return_tensors="pt")
    
    # Move to device with correct dtype
    if use_gpu and USE_FP16:
        dummy_inputs = {k: v.to(device).half() if v.dtype == torch.float32 else v.to(device) 
                       for k, v in dummy_inputs.items()}
    else:
        dummy_inputs = {k: v.to(device) for k, v in dummy_inputs.items()}
    
    # Multiple warmup passes for torch.compile
    for i in range(3):
        with torch.no_grad():
            _ = model(**dummy_inputs)
    
    # Cleanup
    del dummy_inputs, dummy_image
    if use_gpu:
        torch.cuda.empty_cache()
    
    logger.info(f"Model fully optimized on {device}")
    logger.info(f"  - FP16: {USE_FP16 and use_gpu}")
    logger.info(f"  - torch.compile: {USE_TORCH_COMPILE and hasattr(torch, 'compile')}")
    logger.info(f"  - BetterTransformer: {USE_BETTER_TRANSFORMER}")
    logger.info(f"  - Batch size: {BATCH_SIZE}")
    logger.info(f"  - Embedding dim: {EMBEDDING_DIM}")

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
        bucket_name = os.environ.get("GCS_BUCKET_NAME", "partyscene")
        logger.info(f"Initializing GCS connection to bucket: {bucket_name}")
        
        try:
            # GCS authentication for batch jobs
            from obstore.auth.google import GoogleCredentialProvider
            credential_provider = GoogleCredentialProvider()
            self.OBS_STORE = obs.store.GCSStore(
                bucket_name,
                credential_provider=credential_provider
            )
            logger.info("GCS Store initialized with GoogleCredentialProvider")
        except Exception as e:
            logger.warning(f"Failed to use GoogleCredentialProvider, using default: {e}")
            self.OBS_STORE = obs.store.GCSStore(bucket_name)
            logger.info("GCS Store initialized with default auth")

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

    async def save_batch(self, filenames: List[str], embeddings_list: List[List[float]]):
        """Saves batch of embeddings to SurrealDB."""
        if len(filenames) != len(embeddings_list):
            raise ValueError("Filenames and embeddings list length mismatch")
        
        try:
            async with self.db_session() as db:
                # Batch update
                for filename, embeddings in zip(filenames, embeddings_list):
                    if len(embeddings) != EMBEDDING_DIM:
                        logger.error(f"Embedding dimension mismatch for {filename}")
                        continue
                    
                    await db.query(
                        "UPDATE media SET embeddings = $embeddings, status = 'completed', processed_at = time::now() WHERE filename = $filename",
                        {"filename": filename, "embeddings": embeddings},
                    )
            logger.info(f"Successfully saved {len(filenames)} embeddings")
        except Exception as e:
            logger.error(f"Batch save failed", exc_info=True)
            raise
    
    async def save(self, filename: str, embeddings: list):
        """Single save wrapper."""
        await self.save_batch([filename], [embeddings])

    async def fetch_media_objects(self, limit: int = None):
        """Fetch pending media objects from database."""
        try:
            async with self.db_session() as db:
                query = "SELECT filename, id FROM media WHERE status = 'pending' OR status = 'failed'"
                if limit:
                    query += f" LIMIT {limit}"
                
                result = await db.query(query)
                
                # Unwrap SurrealDB response
                if result and len(result) > 0:
                    media_list = result[0] if isinstance(result[0], list) else result
                    logger.info(f"Fetched {len(media_list)} pending media objects")
                    return media_list
                else:
                    logger.info("No pending media objects found")
                    return []
        except Exception as e:
            logger.error(f"Database fetch failed", exc_info=True)
            raise

    async def download_image(self, filename: str) -> bytes:
        """Download single image from GCS with detailed error handling."""
        try:
            logger.debug(f"Downloading: {filename}")
            obs_result = await obs.get_async(self.OBS_STORE, filename)
            image_bytes = bytes(await obs_result.bytes_async())
            logger.debug(f"Downloaded {len(image_bytes)} bytes for {filename}")
            return image_bytes
        except Exception as e:
            logger.error(f"GCS download failed for {filename}: {type(e).__name__} - {e}", exc_info=True)
            raise
    
    async def process_batch(self, media_batch: List[Dict]):
        """Process a batch of media objects."""
        if not media_batch:
            return
        
        filenames = [obj["filename"] for obj in media_batch]
        logger.info(f"Processing batch of {len(filenames)} images")
        
        # Download all images in parallel
        download_tasks = [self.download_image(fn) for fn in filenames]
        download_results = await asyncio.gather(*download_tasks, return_exceptions=True)
        
        # Filter successful downloads
        valid_images = []
        valid_filenames = []
        for idx, result in enumerate(download_results):
            if isinstance(result, Exception):
                logger.error(f"Skipping {filenames[idx]} due to download error")
                # Mark as failed in DB
                try:
                    async with self.db_session() as db:
                        await db.query(
                            "UPDATE media SET status = 'failed', error = $error WHERE filename = $filename",
                            {"filename": filenames[idx], "error": str(result)}
                        )
                except Exception as e:
                    logger.error(f"Failed to mark {filenames[idx]} as failed: {e}")
            else:
                valid_images.append(result)
                valid_filenames.append(filenames[idx])
        
        if not valid_images:
            logger.warning("No valid images in batch after downloads")
            return
        
        # Extract embeddings for entire batch
        try:
            embeddings_list = await extract_embeddings_batch(valid_images)
            logger.info(f"Generated {len(embeddings_list)} embeddings")
            
            # Save all embeddings
            await self.save_batch(valid_filenames, embeddings_list)
            logger.info(f"Successfully processed batch of {len(valid_filenames)} images")
        except Exception as e:
            logger.error(f"Batch processing failed: {e}", exc_info=True)
            raise
    
    async def process(self):
        """Main processing loop with batching."""
        logger.info("Starting media processing job")
        
        # Fetch all pending media
        media_objects = await self.fetch_media_objects()
        
        if not media_objects:
            logger.info("No media to process")
            return
        
        total_processed = 0
        
        # Process in batches
        for i in range(0, len(media_objects), BATCH_SIZE):
            batch = media_objects[i:i+BATCH_SIZE]
            logger.info(f"Processing batch {i//BATCH_SIZE + 1}/{(len(media_objects) + BATCH_SIZE - 1)//BATCH_SIZE}")
            
            try:
                await self.process_batch(batch)
                total_processed += len(batch)
            except Exception as e:
                logger.error(f"Batch {i//BATCH_SIZE + 1} failed, continuing...", exc_info=True)
                continue
        
        logger.info(f"Processing complete. Processed {total_processed}/{len(media_objects)} media objects")


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
