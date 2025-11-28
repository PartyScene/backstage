from quart import Quart
from surrealdb import AsyncSurreal
from surrealdb.data import GeometryPoint, RecordID, Table
from purreal import SurrealDBPoolManager, SurrealDBConnectionPool
import os
from typing import Optional, List, Dict, Any
from shared.utils import record_id_to_json, report_resource
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

    async def _report_resource(self, data: dict):
        """
        Report this resource which is an event
        Args:
            data (dict): The data to report
        """
        return await report_resource(self.pool, data, resource_table="events")

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
        coordinates = tuple(float(x) for x in coordinates)

        try:
            data["creator"] = data["host"] = RecordID("users", data["host"])
            data["location"] = {
                "address": data.get("location"),
                "coordinates": GeometryPoint.parse_coordinates(coordinates),
            }

            # Extract and clean data before event creation
            event_id = data.pop("event_id", None)
            filenames = data.pop("filenames", None)
            types = data.pop("types", None)
            data.pop("id", None)
            data.pop("filename", None)
            data.pop("type", None)
            data.pop("categories[]", None)
            data.pop("coordinates[]", None)

            # Create the event FIRST to get the actual event ID
            async with self.pool.acquire() as conn:
                result = await conn.create(event_id, data)
                if isinstance(result, str):
                    raise Exception(f"Error creating event: {result}")
                
                if not isinstance(result, dict):
                    raise Exception(f"Unexpected result type: {type(result)}")
                
                # Use the newly created event's ID
                created_event_id = result["id"]
                self.logger.warning(
                    f"Created event: {json.dumps(result, option=json.OPT_INDENT_2, default=str)}"
                )

                # Now create media records with the CORRECT event ID
                media_ids = []
                
                for i, filename in enumerate(filenames):
                    media_type = types[i]
                    
                    media_query_result = await conn.create(
                        "media",
                        {
                            "filename": filename,
                            "type": media_type,
                            "creator": data["creator"],
                            "event": created_event_id,
                        },
                    )
                    if isinstance(media_query_result, dict):
                        media_ids.append(media_query_result["id"])
                    self.logger.warning(
                        f"Created media: {json.dumps(media_query_result, option=json.OPT_INDENT_2, default=str)}"
                    )

                # Create individual RELATE statements for each media item
                for media_id in media_ids:
                    relation_result = await conn.query(
                        "RELATE $event -> has_media -> $media",
                        {
                            "event": created_event_id,
                            "media": media_id,
                        },
                    )
                    self.logger.info(
                        f"Created relation: {created_event_id} -> has_media -> {media_id}"
                    )
                self.logger.info(f"Created {len(media_ids)} media relations for event {created_event_id}")
                result = await conn.select(created_event_id)

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
            result = await conn.query(
                "DELETE type::thing('events', $event_id) RETURN BEFORE;",
                {"event_id": event_id}
            )
            return record_id_to_json(result)

    async def fetch_by_distance(
        self,
        coordinates: tuple[float, float],
        distance: int,
        *,
        live: bool = False,
        is_private: bool = False,
        user: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch all events within a certain distance.

        Args:
            coordinates (tuple[float, float]): Latitude and longitude
            distance (int): The distance in meters
            live (bool, optional): If True, only return live events. Defaults to False.
            is_private (bool, optional): If True, only return private events. Defaults to False.


        Returns:
            List[Dict[str, Any]]: List of events within the specified distance
        """
        try:
            async with self.pool.acquire() as conn:
                if user:
                    result = await conn.query(
                        f"""
                        RETURN fn::fetch_events_by_location($coordinates, $distance, $is_live, $is_private, $user);
                        """,
                        {
                            "user": RecordID("users", user),
                            "is_live": live,
                            "distance": distance,
                            "coordinates": GeometryPoint.parse_coordinates(coordinates),
                            "is_private": is_private,
                        },
                    )
                else:
                    result = await conn.query(
                        f"""
                        RETURN fn::fetch_events_by_location($coordinates, $distance, $is_live);
                        """,
                        {
                            "is_live": live,
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
                    RETURN fn::fetch_public_events($page, $limit);
                    """,
                    {"page": page, "limit": limit},
                )
            self.logger.debug(json.dumps(result, option=json.OPT_INDENT_2, default=str))
            return record_id_to_json(result)

        except Exception as e:
            self.logger.error(f"Failed to fetch all events: {str(e)}")
            raise

    async def fetch_private(
        self, user, page: int = 1, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Fetch private events.

        Args:
            user (str): The user ID to fetch private events for.
            page (int, optional): The page number. Defaults to 1.
            limit (int, optional): The number of events per page. Defaults to 20.

        Returns:
            List[Dict[str, Any]]: List of private events
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    RETURN fn::fetch_private_events_for_user($user, $page, $limit);
                    """,
                    {"user": RecordID("users", user), "page": page, "limit": limit},
                )
            self.logger.debug(json.dumps(result, option=json.OPT_INDENT_2, default=str))
            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to fetch all private events: {str(e)}")
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
            return conn.subscribe_live(live_id)

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
            result = await conn.query(
                "UPDATE type::thing('events', $event_id) MERGE $data RETURN AFTER;",
                {"event_id": event_id, "data": data}
            )
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
            update_data: dict[str, Any] = {
                "status": status,
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

    async def create_attendance(self, data: Dict[str, Any]) -> Dict[str, Any]:
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
                await self._create_ticket(data, is_free=True)


            if "err" in result:
                raise Exception(f"Error creating attendance: {result}")
            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to create attendance: {str(e)}")
            raise
        
    async def _create_ticket(self, data, is_free: bool = False):
        """
        Create a ticket in the database.

        Args:
            data (dict): The ticket data to create

        Returns:
            dict: The created ticket object
        """
        data["user"] = RecordID("users", data.pop("user"))
        data["event"] = RecordID("events", data.pop("event"))
        data["is_free"] = is_free

        try:
            async with self.pool.acquire() as conn:
                result = await conn.create("tickets", data)
            return record_id_to_json(result)

        except Exception as e:
            self.logger.error(f"Failed to create ticket: {str(e)}")
            raise

    async def fetch_event_guestlist(self, event_id: str) -> List[Dict[str, Any]]:
        """
        Fetch the guestlist for an event.

        Args:
            event_id (str): The event ID to fetch guestlist for

        Returns:
            List[Dict[str, Any]]: List of guestlist entries with user details and invitation info
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    RETURN fn::fetch_event_guestlist(type::thing('events', $event_id));
                    """,
                    {"event_id": event_id},
                )
            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to fetch event guestlist: {str(e)}")
            raise

    async def add_to_guestlist(self, event_id: str, user_id: str, invited_by: str, status: str = "invited") -> Dict[str, Any]:
        """
        Add a user to an event's guestlist.

        Args:
            event_id (str): The event ID
            user_id (str): The user ID to add to guestlist
            invited_by (str): The ID of the user doing the inviting
            status (str): The invitation status (default: "invited")

        Returns:
            Dict[str, Any]: The created guestlist entry
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    RELATE type::thing('users', $user_id) -> guestlists -> type::thing('events', $event_id) 
                    SET 
                        invited_by = type::thing('users', $invited_by),
                        status = $status;
                    """,
                    {
                        "user_id": user_id,
                        "event_id": event_id,
                        "invited_by": invited_by,
                        "status": status,
                    },
                )
            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to add user to guestlist: {str(e)}")
            raise

    async def remove_from_guestlist(self, event_id: str, user_id: str) -> bool:
        """
        Remove a user from an event's guestlist.

        Args:
            event_id (str): The event ID
            user_id (str): The user ID to remove from guestlist

        Returns:
            bool: True if removal was successful
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    DELETE guestlists WHERE 
                        in = type::thing('users', $user_id) AND 
                        out = type::thing('events', $event_id);
                    """,
                    {"user_id": user_id, "event_id": event_id},
                )
            return True
        except Exception as e:
            self.logger.error(f"Failed to remove user from guestlist: {str(e)}")
            return False

    async def update_guestlist_status(self, event_id: str, user_id: str, status: str) -> Dict[str, Any]:
        """
        Update the status of a guestlist entry.

        Args:
            event_id (str): The event ID
            user_id (str): The user ID
            status (str): The new status ("invited", "accepted", "declined")

        Returns:
            Dict[str, Any]: The updated guestlist entry
        """
        try:
            valid_statuses = ["invited", "accepted", "declined"]
            if status not in valid_statuses:
                raise ValueError(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
                
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    UPDATE guestlists 
                    SET status = $status 
                    WHERE in = type::thing('users', $user_id) AND out = type::thing('events', $event_id)
                    RETURN AFTER;
                    """,
                    {"user_id": user_id, "event_id": event_id, "status": status},
                )
            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to update guestlist status: {str(e)}")
            raise

    async def verify_ticket(self, event_id: str, ticket_number: str) -> Dict[str, Any]:
        """
        Verify and check-in a ticket by its ticket number.

        Args:
            event_id (str): The event ID
            ticket_number (str): The ticket number from QR code

        Returns:
            Dict[str, Any]: Verification result with ticket details and status
        """
        try:
            async with self.pool.acquire() as conn:
                raw_response = await conn.query_raw(
                    """
                    LET $ticket = (
                        SELECT 
                            id,
                            ticket_number,
                            checked_in_at,
                            user.{id, organization_name, first_name, last_name, avatar} AS user,
                            event.{id, title} AS event
                        FROM tickets 
                        WHERE 
                            ticket_number = $ticket_number AND 
                            event = type::thing('events', $event_id)
                        LIMIT 1
                    )[0];
                    
                    RETURN IF $ticket {
                        IF $ticket.checked_in_at {
                            {
                                valid: true,
                                already_checked_in: true,
                                checked_in_at: $ticket.checked_in_at,
                                ticket: $ticket
                            }
                        } ELSE {
                            UPDATE tickets 
                            SET checked_in_at = time::now() 
                            WHERE id = $ticket.id;
                            
                            {
                                valid: true,
                                already_checked_in: false,
                                checked_in_at: time::now(),
                                ticket: $ticket
                            }
                        }
                    } ELSE {
                        {
                            valid: false,
                            message: "Ticket not found or does not belong to this event"
                        }
                    };
                    """,
                    {"event_id": event_id, "ticket_number": ticket_number},
                )
                
                # query_raw() returns: {'id': '...', 'result': [{}, {}]}
                # Multiple statements return array of results - last item is RETURN statement
                # Structure: raw_response['result'][-1]['result'] contains our data
                if raw_response and 'result' in raw_response and len(raw_response['result']) > 0:
                    result = raw_response['result'][-1].get('result')
                else:
                    result = None
                    
            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to verify ticket: {str(e)}")
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
        min_connections=3,
        max_connections=20,  # Increased from 10 to handle more concurrent requests
        max_idle_time=60,  # Reduced from 300s - recycle idle connections faster
        connection_timeout=10.0,  # Increased from 5s to allow slower connection establishment
        acquisition_timeout=30.0,  # Increased from 10s to 30s to prevent premature cancellation
        health_check_interval=10,  # Reduced from 30s - check health more frequently
        max_usage_count=100,  # Reduced from 1000 - recycle connections more aggressively
        connection_retry_attempts=3,
        connection_retry_delay=1.0,
        schema_file=SCHEMA_FILE,
        reset_on_return=True,
        log_queries=True,
    )

    # Create EventsDB instance
    events_db = EventsDB(pool, app.logger)

    return events_db, pool_manager
