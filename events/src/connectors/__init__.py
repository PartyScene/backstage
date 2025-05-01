from quart import Quart
from surrealdb import AsyncSurreal
from surrealdb.data import GeometryPoint, RecordID, Table
from purreal import SurrealDBPoolManager, SurrealDBConnectionPool
import os
from typing import Optional, List, Dict, Any
from shared.utils import record_id_to_json
import orjson as json


class EventsDB:
    def __init__(self, pool: SurrealDBConnectionPool, logger) -> None:
        """
        Initialize the EventsDB class.
        Args:
            pool (SurrealDBConnectionPool): The connection pool for the database
            logger: The logger instance
        """
        self.pool = pool
        self.logger = logger

    async def _info(self):
        """
        Get database information.

        Returns:
            Any: Database information
        """
        return await self.pool.execute_query("INFO FOR DB")

    def subset(self, d, keys):
        """
        Get a subset of a dictionary.

        Args:
            d (Dict): The dictionary
            keys (List): The keys to include in the subset

        Returns:
            Dict: The subset of the dictionary
        """
        return {k: d[k] for k in keys if k in d}

    async def create_event(self, data: Dict[str, Any]):
        """
        Create a new event.

        Args:
            data (Dict[str, Any]): The data for the event

        Returns:
            Dict[str, Any]: The created event
        """
        coordinates = data.pop("coordinates")

        try:
            data["creator"] = data["host"] = RecordID("users", data["host"])
            data["location"] = {
                "address": data.get("location"),
                "coordinates": {"type": "Point", "coordinates": coordinates},
            }

            media_ids = []
            for i, filename in enumerate(data["filenames"]):
                data["filename"] = filename
                data["type"] = data["types"][i]
                async with self.pool.acquire() as conn:
                    media_query_result = await conn.create(
                        "media",
                        {
                            "filename": filename,
                            "type": data["types"][i],
                            "creator": data["creator"],
                            "event": data["event_id"],
                        },
                    )
                    media_ids.append(media_query_result["id"])
                self.logger.warning(
                    json.dumps(
                        media_query_result, option=json.OPT_INDENT_2, default=str
                    )
                )

            data.pop("id", None)
            data.pop("filenames", None)
            data.pop("filename", None)
            data.pop("type", None)
            data.pop("categories[]", None)
            data.pop("coordinates[]", None)
            data.pop("types", None)

            async with self.pool.acquire() as conn:
                event_id = data.pop("event_id", None)
                result = await conn.create(event_id, data)

                await conn.query(
                    "RELATE $event -> has_media -> $media_ids",
                    {
                        "event": result["id"],
                        "media_ids": media_ids,
                    },
                )
                self.logger.warning(
                    json.dumps(result, option=json.OPT_INDENT_2, default=str)
                )
                result = await conn.select(result["id"])
            if isinstance(result, str):
                raise Exception(f"Error creating event: {result}")
            return record_id_to_json(result)

        except Exception as e:
            self.logger.error(f"Failed to create event: {str(e)}")
            raise

    async def delete_event(self, event_id: str):
        """
        Delete an event by ID.

        Args:
            event_id (str): The ID of the event to delete

        Returns:
            Dict[str, Any]: The deleted event
        """
        async with self.pool.acquire() as conn:
            result = await conn.delete(RecordID("events", event_id))
            if "err" in result:
                raise Exception(f"Error deleting event: {result}")
        return record_id_to_json(result)

    async def fetch_by_distance(
        self, coordinates: tuple[float, float], distance: int, *, live: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Fetch all events within a certain distance.

        Args:
            coordinates (tuple[float, float]): Latitude and longitude
            distance (int): The distance in meters
            live (bool, optional): If True, only return live events

        Returns:
            List[Dict[str, Any]]: List of events within the specified distance
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    RETURN fn::fetch_events_by_location($coordinates, $distance, $live);
                    """,
                    {
                        "live": live,
                        "distance": distance,
                        "coordinates": GeometryPoint.parse_coordinates(coordinates),
                    },
                )
            return record_id_to_json(result)

        except Exception as e:
            self.logger.error(f"Failed to fetch events by distance: {str(e)}")
            raise

    async def fetch_all(self, page: int = 1, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Fetch all events with their attendees.

        Args:
            page (int, optional): The page number. Defaults to 1.
            limit (int, optional): The number of events per page. Defaults to 20.

        Returns:
            List[Dict[str, Any]]: List of all events
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    RETURN fn::fetch_all_events($page, $limit, false);
                    """,
                    {"page": page, "limit": limit},
                )
            self.logger.debug(json.dumps(result, option=json.OPT_INDENT_2, default=str))
            return record_id_to_json(result)

        except Exception as e:
            self.logger.error(f"Failed to fetch all events: {str(e)}")
            raise

    async def fetch_private(
        self, page: int = 1, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Fetch private events.

        Args:
            page (int, optional): The page number. Defaults to 1.
            limit (int, optional): The number of events per page. Defaults to 20.

        Returns:
            List[Dict[str, Any]]: List of public events
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    RETURN fn::fetch_all_events($page, $limit, true);
                    """,
                    {"page": page, "limit": limit},
                )
            self.logger.debug(json.dumps(result, option=json.OPT_INDENT_2, default=str))
            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to fetch all public events: {str(e)}")
            raise

    async def fetch(self, event_id: str) -> Optional[Dict[str, Any]]:
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

    async def live_query(self, event_id: str):
        """
        Start a live query for an event.

        Args:
            event_id (str): The ID of the event

        Returns:
            Dict[str, Any]: The live query result
        """
        try:
            query = """
            LIVE SELECT 
                *,
                <-attends<-users AS attendees,
                array::len(<-attends<-users) as attendees_count
            OMIT embeddings
            FROM type::thing('events', $event_id)
            FETCH host, attendees;
            """
            async with self.pool.acquire() as conn:
                result = await conn.query(query, {"event_id": event_id})
            self.logger.debug(json.dumps(result, option=json.OPT_INDENT_2, default=str))
            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to create live query: {str(e)}")
            raise

    async def get_live_notifications(self, live_id: str):
        """
        Get notifications for a live query.

        Args:
            live_id (str): The ID of the live query

        Returns:
            Any: The live query notifications
        """
        async with self.pool.acquire() as conn:
            return await conn.subscribe_live(live_id)

    async def kill_live_query(self, live_id: str):
        """
        Kill a live query.

        Args:
            live_id (str): The ID of the live query
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.kill(live_id)
        except Exception as e:
            self.logger.error(f"Failed to kill live query: {str(e)}")
            raise

    async def update_event_data(self, event_id: str, data: dict):
        """
        Update the data of an event.

        Args:
            event_id (str): The ID of the event to update
            data (dict, optional): The metadata to change

        Returns:
            Dict[str, Any]: The updated event data
        """
        async with self.pool.acquire() as conn:
            result = await conn.merge(RecordID("events", event_id), data)
            if result and "ERR" in result:
                raise Exception(f"Error updating event: {result}")
            self.logger.debug(json.dumps(result, option=json.OPT_INDENT_2, default=str))
            return record_id_to_json(result)

    async def update_event_status(
        self, event_id: str, status: str, metadata: dict = {}
    ) -> Dict[str, Any]:
        """
        Update the status of an event and optionally add metadata.

        Args:
            event_id (str): The ID of the event to update
            status (str): The new status ('scheduled', 'live', 'ended', 'cancelled')
            metadata (dict, optional): Additional metadata about the status change

        Returns:
            Dict[str, Any]: The updated event data
        """
        try:
            # Validate status
            valid_statuses = ["scheduled", "live", "ended", "cancelled"]
            if status not in valid_statuses:
                raise ValueError(
                    f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                )

            # Build update query
            update_data = {
                "status": status,
                "updated_at": "time::now()",
            }
            if metadata:
                update_data["metadata"] = metadata

            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    UPDATE ONLY type::thing('events', $event_id) MERGE $update_data
                    RETURN 
                        *,
                        <-attends<-users AS attendees,
                        array::len(<-attends<-users) as attendees_count;
                    """,
                    {"event_id": event_id, "update_data": update_data},
                )
            return record_id_to_json(result)

        except Exception as e:
            self.logger.error(f"Failed to update event status: {str(e)}")
            raise

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
            if "err" in result:
                raise Exception(f"Error creating attendance: {result}")
        except Exception as e:
            self.logger.error(f"Failed to create attendance: {str(e)}")
            raise


async def init_db(app) -> tuple[EventsDB, SurrealDBPoolManager]:
    """
    Initialize the database connection pool and return an EventsDB instance.

    Args:
        app: The Quart application instance

    Returns:
        tuple[EventsDB, SurrealDBPoolManager]: The initialized database connector and pool manager
    """
    SCHEMA_FILE = os.getenv("SCHEMA_FILE")
    SURREAL_URI = os.getenv("SURREAL_URI")
    SURREAL_USER = os.getenv("SURREAL_USER")
    SURREAL_PASS = os.getenv("SURREAL_PASS")
    NAMESPACE = "partyscene"
    DATABASE = "partyscene"

    # Create connection pool manager
    pool_manager = SurrealDBPoolManager()

    # Create a connection pool for the events service
    pool = await pool_manager.create_pool(
        name="events_pool",
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

    # Create EventsDB instance
    events_db = EventsDB(pool, app.logger)

    return events_db, pool_manager
