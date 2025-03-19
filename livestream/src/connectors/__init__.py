from quart import Quart
from surrealdb import AsyncSurreal
import os

from shared.utils import record_id_to_json
from purreal import SurrealDBConnectionPool, SurrealDBPoolManager


class LiveStreamDB:
    def __init__(self, pool: SurrealDBConnectionPool) -> None:
        self.pool: SurrealDBConnectionPool = pool

    async def fetch_livestream(self, event_id: str):
        """
        Get the current livestream data attached to an event
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                SELECT * FROM ONLY livestreams WHERE event = type::thing("events", $event_id)
                """,
                {"event_id": event_id},
            )
        return record_id_to_json(result)

    async def store_livestream(self, channel_response, input_response, event_id: str):
        """
        Store the ingest url / playback url / from GCP and attach it to the event.

        Returns:
            bool: Indicates if this operation was a success
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                INSERT INTO livestreams 
                    (channel_name, input_name, ingest_url, playback_url, manifests, event) VALUES ($channel_name, $input_name, $ingest_url, $playback_url, $manifests, type::thing("events", $event_id))
                """,
                {
                    "channel_name": channel_response.name,
                    "input_name": input_response.name,
                    "ingest_url": input_response.uri,
                    "playback_url": channel_response.output.uri,
                    "manifests": [x.file_name for x in channel_response.manifests],
                    "event_id": event_id,
                },
            )
        return record_id_to_json(result[0])

    # async def delete(self, email) :
    #     """This db function deletes a user.

    #     Args:
    #         email (__string_): The user email to delete.
    #     """
    #     result = await self.db.query(
    #         "DELETE users WHERE email = $email;", {"email": email}
    #     )
    #     return result[0]["result"][0]

    # async def update(self, data: dict):
    #     """This function updates a specific field

    #     Args:
    #         data (dict): _description_
    #     """
    #     record_id = (
    #         await self.db.query(
    #             "SELECT id FROM users WHERE email = $email;",
    #             {"email": data["email"]},
    #         )
    #     )[0]["result"][0]["id"]
    #     result = await self.db.query(
    #         "UPDATE $record_id MERGE $content",
    #         {"content": data, "record_id": record_id},
    #     )
    #     return result


async def init_db(app) -> LiveStreamDB:
    """
    Initialize the database connection pool and return an LiveStreamDB instance.

    Args:
        app: The Quart application instance

    Returns:
        LiveStreamDB: Initialized database connector
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
        name="scenes_pool",
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
        connection_retry_delay=2.0,
        schema_file=SCHEMA_FILE,
        reset_on_return=True,
        log_queries=True,
    )

    # Create LiveStreamDB instance
    livestream_db = LiveStreamDB(pool)

    # For backward compatibility with existing code
    # This allows code that directly accesses LiveStreamDB.db to still work
    async with pool.acquire() as conn:
        livestream_db.pool = conn

    return livestream_db, pool_manager
