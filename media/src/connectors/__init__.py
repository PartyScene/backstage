from quart import Quart
import os
from surrealdb import RecordID
from shared.utils import record_id_to_json
from purreal import SurrealDBPoolManager, SurrealDBConnectionPool


class MediaDB:

    def __init__(self, pool: SurrealDBConnectionPool) -> None:
        self.pool: SurrealDBConnectionPool = pool

    async def _info(self):
        """Get database information."""
        return await self.pool.execute_query("INFO FOR DB")

    async def fetch_media(self, data) -> dict:
        """Fetch media record from the database by its unique ID."""
        async with self.pool.acquire() as conn:
            result = await conn.select(RecordID("media", data["id"]))
        return record_id_to_json(result)

    async def delete_media(self, data: dict):
        """Delete a media record by ID.

        Args:
            data (dict): Must contain media ID.
        """
        async with self.pool.acquire() as conn:
            result = await conn.delete(RecordID("media", data["id"]))
        return result

    async def create_media_metadata(self, data: dict) -> dict:
        """Create initial media record in the database.

        Args:
            data (dict): Must contain type, filename, creator, event.
        """
        async with self.pool.acquire() as conn:
            query = """
            CREATE ONLY media SET
                type     = $type,
                filename = $filename,
                creator  = type::thing('users', $creator),
                event    = type::thing('events', $event)
            RETURN AFTER;
            """
            result = await conn.query(query, data)

            if isinstance(result, dict):
                return record_id_to_json(result)
            else:
                raise Exception(f"Error creating media record: {result}")

    async def update_media_metadata(self, media_id: str, metadata: dict) -> dict:
        """
        Patch ffprobe/Pillow metadata onto an existing media record after compression.

        Stores a nested `metadata` object on the record so ffprobe fields are
        namespaced and don't collide with top-level media fields.

        Args:
            media_id (str): The media record ID (bare string, not a RecordID).
            metadata (dict): Extracted media metadata from ffprobe or Pillow.

        Returns:
            dict: The updated media record.
        """
        async with self.pool.acquire() as conn:
            query = """
            UPDATE ONLY type::thing('media', $media_id)
            SET metadata = $metadata
            RETURN AFTER;
            """
            result = await conn.query(query, {
                "media_id": media_id,
                "metadata": metadata,
            })

            if isinstance(result, dict):
                return record_id_to_json(result)
            else:
                raise Exception(f"Error updating media metadata for {media_id}: {result}")


async def init_db(app) -> MediaDB:
    """
    Initialize the database connection pool and return a MediaDB instance.

    Args:
        app: The Quart application instance.

    Returns:
        tuple[MediaDB, SurrealDBPoolManager]
    """
    SCHEMA_FILE = os.getenv("SCHEMA_FILE")
    SURREAL_URI = os.getenv("SURREAL_URI")
    SURREAL_USER = os.getenv("SURREAL_USER")
    SURREAL_PASS = os.getenv("SURREAL_PASS")
    NAMESPACE = "partyscene"
    DATABASE = "partyscene"

    pool_manager = SurrealDBPoolManager()

    pool = await pool_manager.create_pool(
        name="media_pool",
        uri=SURREAL_URI,
        credentials={"username": SURREAL_USER, "password": SURREAL_PASS},
        namespace=NAMESPACE,
        database=DATABASE,
        min_connections=3,
        max_connections=20,
        max_idle_time=60,
        connection_timeout=10.0,
        acquisition_timeout=30.0,
        health_check_interval=10,
        max_usage_count=100,
        connection_retry_attempts=3,
        connection_retry_delay=1.0,
        schema_file=SCHEMA_FILE,
        reset_on_return=True,
        log_queries=True,
    )

    media_db = MediaDB(pool)
    return media_db, pool_manager