import os
import io
import asyncio
import logging  # Import standard logging
from typing import List, Dict
from contextlib import asynccontextmanager

# Force HuggingFace to use the model baked into the Docker image at build time.
# Prevents unauthenticated network requests to HF Hub at runtime, which are
# rate-limited and slow. Model is pre-downloaded to HF_HOME in the Dockerfile.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

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
# Revision pinned to the last known-good commit on the main branch.
# To get the current HEAD: huggingface_hub.model_info("google/vit-base-patch16-224-in21k").sha
# Leave as None to always pull latest (less secure but easier to update).
VIT_MODEL_REVISION = None  # e.g. "3f23b6b..."
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


async def extract_embeddings_batch(image_bytes_list: List[bytes]) -> tuple:
    """
    Extract embeddings for a batch of images.

    Returns:
        Tuple of (valid_indices, embeddings_list).
        valid_indices: positions in image_bytes_list that decoded successfully.
        embeddings_list: one 768-dim vector per valid image, same order.

        IMPORTANT: callers must use valid_indices to re-align their filename list
        before saving — PIL silently drops undecodable images so the embedding
        list is shorter than the input list when any images fail.
    """
    if not processor or not model or not device:
        logger.critical("Model resources not initialized during embedding extraction.")
        raise RuntimeError("Model resources not initialized.")

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
        return [], []

    inputs = processor(images=images, return_tensors="pt")
    if device.type == "cuda" and USE_FP16:
        inputs = {k: v.to(device).half() if v.dtype == torch.float32 else v.to(device)
                 for k, v in inputs.items()}
    else:
        inputs = {k: v.to(device) for k, v in inputs.items()}

    async with model_lock:
        try:
            with torch.no_grad():
                outputs = model(**inputs)
                cls_embeddings = outputs.last_hidden_state[:, 0, :]
        except Exception as e:
            logger.error("Batch model inference failed", exc_info=True)
            raise RuntimeError("Batch inference failed") from e

    embeddings_list = cls_embeddings.float().cpu().tolist()

    if len(embeddings_list) != len(valid_indices):
        raise RuntimeError(
            f"Model output shape mismatch: {len(embeddings_list)} embeddings "
            f"for {len(valid_indices)} valid images"
        )

    return valid_indices, embeddings_list


async def extract_embeddings(image_bytes: bytes) -> List[float]:
    """Single image wrapper. For batches use extract_embeddings_batch() directly."""
    _, embeddings = await extract_embeddings_batch([image_bytes])
    return embeddings[0] if embeddings else []


async def init_globals():
    """Initialize global variables with maximum optimization."""
    global processor, model, device, db_connection, EMBEDDING_DIM
    logger.info("Initializing optimized global resources...")
    
    # Determine device early
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    use_gpu = device.type == "cuda"
    logger.info(f"Target device: {device}")
    
    # Load processor (lightweight, no optimization needed)
    proc_kwargs = {}
    if VIT_MODEL_REVISION:
        proc_kwargs["revision"] = VIT_MODEL_REVISION
    processor = ViTImageProcessor.from_pretrained(VIT_MODEL_NAME, **proc_kwargs)
    logger.info("Processor loaded")
    
    # Optimized model loading
    load_kwargs = {
        "output_hidden_states": False,
        "low_cpu_mem_usage": True,  # Reduces memory during loading
    }
    if VIT_MODEL_REVISION:
        load_kwargs["revision"] = VIT_MODEL_REVISION
    
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
    
    # Always move the model to the target device.
    # When loading with torch_dtype=float16 via from_pretrained, the weights are
    # already in FP16 but the model is still on CPU — .to(device) is still required.
    model = model.to(device)
    
    model.eval()  # Evaluation mode
    
    # PyTorch 2.0+ optimization: torch.compile
    # GPU only — the inductor backend requires Triton (CUDA) or a C++ toolchain.
    # Neither is present on GCP Batch CPU VMs, causing a crash during the first
    # forward pass even though compile() itself appears to succeed.
    if USE_TORCH_COMPILE and use_gpu and hasattr(torch, "compile"):
        try:
            logger.info("Compiling model with torch.compile()...")
            model = torch.compile(
                model,
                mode="reduce-overhead",  # Best for batch inference
                fullgraph=False          # More compatible
            )
            logger.info("Model compiled successfully")
        except Exception as e:
            logger.warning(f"torch.compile failed, continuing without: {e}")
    elif USE_TORCH_COMPILE and not use_gpu:
        logger.info("Skipping torch.compile — CPU-only runtime, inductor not available")
    
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
            await db_connection.connect(SURREAL_URI)  # Explicitly open the WS connection
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
                query = """
                    SELECT filename, id FROM media 
                    WHERE (status = 'pending' OR status = 'failed')
                    AND type IN ['image/jpeg','image/jpg','image/png','image/heic','image/heif','image/webp']
                """
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
            obs_result = await self.OBS_STORE.get_async(filename)
            image_bytes = await obs_result.bytes_async()
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
        
        # Extract embeddings for entire batch.
        # valid_indices tells us which positions in valid_images decoded OK —
        # PIL silently drops corrupt/unreadable files, so the embedding list
        # can be shorter than valid_images. We re-align valid_filenames using
        # those indices before saving to guarantee a 1-to-1 match.
        try:
            decoded_indices, embeddings_list = await extract_embeddings_batch(valid_images)
            logger.info(
                f"Generated {len(embeddings_list)} embeddings from "
                f"{len(valid_images)} downloaded images "
                f"({len(valid_images) - len(embeddings_list)} failed PIL decode)"
            )

            # Re-align filenames to only those whose images actually decoded.
            aligned_filenames = [valid_filenames[i] for i in decoded_indices]

            await self.save_batch(aligned_filenames, embeddings_list)
            logger.info(f"Successfully saved {len(aligned_filenames)} embeddings")
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