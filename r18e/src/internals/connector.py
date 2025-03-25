import os
import json

from quart import Quart
from surrealdb import AsyncSurreal, RecordID
from shared.utils import record_id_to_json
from purreal import SurrealDBConnectionPool, SurrealDBPoolManager

from typing import Tuple

class R18E:
    def __init__(self, pool: SurrealDBConnectionPool, logger) -> None:
        self.pool = pool
        self.logger = logger

    async def _info(self):
        """Get database information."""
        return await self.pool.execute_query("INFO FOR DB")

    async def store_embedding(self, event_id: str, embedding: list[float]) -> dict:
        """Store an embedding for an event."""

        # self.logger.warning(f"Storing embedding for event {event_id} -- {embedding}")

        data = dict()
        data['embeddings']['media'] = embedding
        async with self.pool.acquire() as conn:
            result = await conn.merge(RecordID('events', event_id), data)
        return result

    async def fetch_embedding(self, event_id: str) -> dict:
        """Fetch an embedding for an event."""
        self.logger.warning(f"Fetching embedding for event {event_id}")
        return await self.pool.execute_query(f"SELECT * FROM embeddings WHERE id = $id", {"id": event_id})

async def init_db(app: Quart) -> Tuple[R18E, SurrealDBPoolManager]:
    """
    Initialize the database connection pool and return an instance.

    Args:
        app: The Quart application instance

    Returns:
        Initialized database connector
    """
    SCHEMA_FILE = os.getenv("SCHEMA_FILE")
    SURREAL_URI = os.getenv("SURREAL_URI")
    SURREAL_USER = os.getenv("SURREAL_USER")
    SURREAL_PASS = os.getenv("SURREAL_PASS")
    NAMESPACE = "partyscene"
    DATABASE = "partyscene"

    # Create connection pool manager
    pool_manager = SurrealDBPoolManager()

    # Create a connection pool for events service
    pool = await pool_manager.create_pool(
        name="r18e_pool",
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

    return R18E(pool, app.logger), pool_manager
