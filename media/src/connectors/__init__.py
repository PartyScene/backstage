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
        """
        Fetch media record from the database by its unique ID.
        """
        async with self.pool.acquire() as conn:
            result = await conn.select(RecordID("media", data["id"]))
        return record_id_to_json(result)

    async def delete_media(self, data: dict):
        """This function deletes media data.

        Args:
            data (__dict__): Must contain media ID.
        """
        async with self.pool.acquire() as conn:
            result = await conn.delete(RecordID("media", data["id"]))
        return result

    async def create_media_metadata(self, data: dict) -> dict:
        """Uploads media metadata to the database

        Args:
            data (dict): _description_
        """

        async with self.pool.acquire() as conn:
            query = """
            CREATE ONLY media SET type = $type, filename = $filename, creator = type::thing('users', $creator), event = type::thing('events', $event) RETURN AFTER;
            """
            result = await conn.query(query, data)
            if "ERR" in result:
                raise Exception(
                    f"Error creating media record: {result}"
                )  # Handle error case
            return record_id_to_json(result)


async def init_db(app) -> MediaDB:
    """
    Initialize the database connection pool and return an MediaDB instance.

    Args:
        app: The Quart application instance

    Returns:
        MediaDB: Initialized database connector
    """
    SCHEMA_FILE = os.getenv("SCHEMA_FILE")
    SURREAL_URI = os.getenv("SURREAL_URI")
    SURREAL_USER = os.getenv("SURREAL_USER")
    SURREAL_PASS = os.getenv("SURREAL_PASS")
    NAMESPACE = "partyscene"
    DATABASE = "partyscene"

    # Create connection pool manager
    pool_manager = SurrealDBPoolManager()

    # Create a connection pool for media service
    pool = await pool_manager.create_pool(
        name="media_pool",
        uri=SURREAL_URI,
        credentials={"username": SURREAL_USER, "password": SURREAL_PASS},
        namespace=NAMESPACE,
        database=DATABASE,
        min_connections=2,
        max_connections=10,
        max_idle_time=300,
        connection_timeout=5.0,
        acquisition_timeout=10.0,
        health_check_interval=30,
        max_usage_count=1000,
        connection_retry_attempts=3,
        connection_retry_delay=1.0,
        schema_file=SCHEMA_FILE,
        reset_on_return=True,
        log_queries=True,
    )

    # Create MediaDB instance
    media_db = MediaDB(pool)

    return media_db, pool_manager
