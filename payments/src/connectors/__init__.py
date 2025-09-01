from quart import Quart
import os
import orjson as json

from surrealdb import RecordID
from typing import Literal, Any, Dict, Optional
from shared.utils import record_id_to_json
from purreal import SurrealDBConnectionPool, SurrealDBPoolManager


class PaymentsDB:

    def __init__(self, pool: SurrealDBConnectionPool, logger) -> None:
        self.pool = pool
        self.logger = logger

    async def _info(self):
        """Get database information."""
        return await self.pool.execute_query("INFO FOR DB")

    def subset(self, d, keys):
        return {k: d[k] for k in keys if k in d}

    async def _update_user(self, data: dict) -> dict:
        """
        Update user data

        Args:
            data (dict): User data to update, must include 'id' field

        Returns:
            dict: Updated user data
        """

        if "filename" in data:
            async with self.pool.acquire() as conn:
                data["creator"] = RecordID("users", data["id"])
                media_query_result = await conn.create(
                    "media", self.subset(data, ["filename", "type", "creator"])
                )
                self.logger.warning(
                    json.dumps(
                        media_query_result, option=json.OPT_INDENT_2, default=str
                    )
                )

                if isinstance(media_query_result, dict):
                    data["avatar"] = media_query_result["id"]

        async with self.pool.acquire() as conn:
            result = await conn.query(
                "UPDATE ONLY type::thing('users', $record_id) MERGE $content RETURN AFTER;",
                {"content": data, "record_id": data["id"]},
            )
        self.logger.info(json.dumps(result, option=json.OPT_INDENT_2, default=str))
        return record_id_to_json(result)

    async def create_attendance(self, data: Dict[str, Any]):
        """
        Create an attendance relationship between a user and an event.

        Args:
            data (Dict[str, Any]): The data for the attendance relationship
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.let("user", RecordID("users", data["user"]))
                await conn.let("event", RecordID("events", data["event"]))
                query = """
                RELATE $user -> attends -> $event SET status = $status;
                """
                result = await conn.query(query, {"status": data["status"]})
            if isinstance(result[0], str):
                raise Exception(f"Error creating attendance: {result}")
            return record_id_to_json(result[0])
        except Exception as e:
            self.logger.error(f"Failed to create attendance: {str(e)}")
            raise

    async def _create_ticket(self, data):
        """
        Create a ticket in the database.

        Args:
            data (dict): The ticket data to create

        Returns:
            dict: The created ticket object
        """
        data["user"] = RecordID("users", data.pop("user"))
        data["event"] = RecordID("events", data.pop("event"))

        try:
            async with self.pool.acquire() as conn:
                result = await conn.create("tickets", data)
            return record_id_to_json(result)

        except Exception as e:
            self.logger.error(f"Failed to create ticket: {str(e)}")
            raise

    async def _fetch(self, event_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single event by ID.

        Args:
            event_id (str): The event ID to fetch

        Returns:
            Optional[Dict[str, Any]]: Event data or None if not found
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    RETURN fn::fetch_event(type::thing('events', $event_id));
                    """,
                    {"event_id": event_id},
                )
            self.logger.debug(json.dumps(result, option=json.OPT_INDENT_2, default=str))
            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to fetch event: {str(e)}")
            raise


async def init_db(app) -> tuple[PaymentsDB, SurrealDBPoolManager]:
    """
    Initialize the database connection pool and return an PaymentsDB instance.

    Args:
        app: The Quart application instance

    Returns:
        PaymentsDB: Initialized database connector
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
        name="payments_pool",
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

    # Create PaymentsDB instance
    payments_db = PaymentsDB(pool, app.logger)

    return payments_db, pool_manager
