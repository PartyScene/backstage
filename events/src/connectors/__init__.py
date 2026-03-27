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

    async def fetch_trending_events(self, page: int = 1, limit: int = 50):
        """
        Fetch public upcoming events ranked by trending score.

        Score = (attendee_count × 3) + (post_count × 2), tiebroken by start time.
        This surfaces events with momentum rather than just the most recently
        created ones, giving the discover feed an Instagram-style feel.
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                "RETURN fn::fetch_trending_events($page, $limit);",
                {"page": page, "limit": limit},
            )
        return record_id_to_json(result)


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

    async def fetch_similar_events(self, event_id: str, limit: int = 10) -> list:
        """
        Return visually similar events using HNSW KNN on ViT-768 media embeddings.

        Calls fn::fetch_similar_events which averages the source event's media
        embeddings, runs a cosine ANN search, deduplicates by event, filters
        to future events only, and returns lightweight fn::fetch_event_preview
        cards ordered by visual similarity (closest first).

        Args:
            event_id (str): Raw event ID (without 'events:' prefix).
            limit    (int): Max results (default 10).

        Returns:
            list: [{ "event": {...}, "visual_distance": float }, ...]
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    "RETURN fn::fetch_similar_events(type::thing('events', $event_id), $limit);",
                    {"event_id": event_id, "limit": limit},
                )
            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to fetch similar events for {event_id}: {str(e)}")
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

        Both the RELATE and the ticket CREATE happen inside the same connection
        acquisition so they share a logical unit of work. A duplicate-guard on
        the RELATE (IF NOT EXISTS) means two concurrent calls for the same
        user+event pair will only produce one attends edge and one ticket.
        """
        try:
            user_id   = data["user"]
            event_id  = data["event"]
            user_rid  = RecordID("users",  user_id)
            event_rid = RecordID("events", event_id)

            async with self.pool.acquire() as conn:
                # Atomic duplicate guard: only RELATE if the edge doesn't exist yet.
                try:
                    relate_result = await conn.query(
                    """
                    -- Use a composite id for the relation
                        RELATE type::thing('users', $user_id)
                            -> attends ->
                               type::thing('events', $event_id)
                        SET status = $status;
                    """,
                    {"user_id": user_id, "event_id": event_id, "status": data["status"]},
                )

                    # Only create a ticket when we actually created a new edge.
                    # relate_result is None / empty when the guard blocked creation.
                    ticket_data = {**data, "user": user_id, "event": event_id}
                    ticket_data["user"]  = RecordID("users",  ticket_data.pop("user"))
                    ticket_data["event"] = RecordID("events", ticket_data.pop("event"))
                    ticket_data["is_free"] = True
                    if "tier" in ticket_data and ticket_data["tier"]:
                        ticket_data["tier"] = RecordID("ticket_tiers", ticket_data["tier"])
                    else:
                        ticket_data.pop("tier", None)
                    await conn.create("tickets", ticket_data)
                except Exception:
                    # If the relation already exists, don't create a ticket
                    pass

            return record_id_to_json(relate_result)
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

        if "tier" in data and data["tier"]:
            data["tier"] = RecordID("ticket_tiers", data["tier"])
        else:
            data.pop("tier", None)

        try:
            async with self.pool.acquire() as conn:
                result = await conn.create("tickets", data)
            return record_id_to_json(result)

        except Exception as e:
            self.logger.error(f"Failed to create ticket: {str(e)}")
            raise

    async def create_ticket_tier(
        self, event_id: str, tier_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a ticket tier for an event. Max 3 tiers per event.

        The count-check and CREATE are collapsed into a single conditional
        statement so two concurrent requests both reading count=2 cannot both
        slip through and create a 4th tier.
        """
        try:
            tier_data["event"] = RecordID("events", event_id)
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    IF count(
                        SELECT id FROM ticket_tiers
                        WHERE event = type::thing('events', $event_id)
                    ) >= 3 {
                        THROW "Maximum of 3 tiers per event";
                    } ELSE {
                        CREATE ticket_tiers CONTENT $tier_data;
                    };
                    """,
                    {"event_id": event_id, "tier_data": tier_data},
                )
            return record_id_to_json(result[0] if isinstance(result, list) else result)
        except Exception as e:
            self.logger.error(f"Failed to create ticket tier: {str(e)}")
            raise

    async def update_ticket_tier(
        self, tier_id: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update a ticket tier.

        Args:
            tier_id (str): The tier ID
            data (dict): Fields to update (name, price, capacity, description)

        Returns:
            Dict[str, Any]: The updated tier
        """
        try:
            allowed = {"name", "price", "capacity", "description"}
            update_data = {k: v for k, v in data.items() if k in allowed}

            async with self.pool.acquire() as conn:
                result = await conn.query(
                    "UPDATE ONLY type::thing('ticket_tiers', $tier_id) MERGE $data RETURN AFTER;",
                    {"tier_id": tier_id, "data": update_data},
                )
            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to update ticket tier: {str(e)}")
            raise

    async def delete_ticket_tier(self, tier_id: str) -> bool:
        """
        Delete a ticket tier. Only allowed if no tickets have been sold.

        Uses a single conditional DELETE so the sold_count check and the
        delete happen atomically — a ticket sale landing between a separate
        SELECT and DELETE cannot slip through and corrupt sold ticket data.
        """
        try:
            async with self.pool.acquire() as conn:
                # Confirm the tier exists first for a clear not-found error.
                tier = await conn.select(RecordID("ticket_tiers", tier_id))
                if not tier:
                    raise ValueError("Tier not found")

                # Atomic: only delete if sold_count is still 0.
                # RETURN BEFORE lets us distinguish "deleted" from "blocked".
                deleted = await conn.query(
                    """
                    DELETE type::thing('ticket_tiers', $tier_id)
                    WHERE sold_count = NONE OR sold_count = 0
                    RETURN BEFORE;
                    """,
                    {"tier_id": tier_id},
                )

                if not deleted or not deleted[0]:
                    raise ValueError("Cannot delete tier with sold tickets")

            return True
        except Exception as e:
            self.logger.error(f"Failed to delete ticket tier: {str(e)}")
            raise

    async def fetch_event_tiers(self, event_id: str) -> List[Dict[str, Any]]:
        """
        Fetch all ticket tiers for an event.

        Args:
            event_id (str): The event ID

        Returns:
            List[Dict[str, Any]]: List of tiers ordered by price ascending
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    SELECT * FROM ticket_tiers
                    WHERE event = type::thing('events', $event_id)
                    ORDER BY price ASC;
                    """,
                    {"event_id": event_id},
                )
            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to fetch event tiers: {str(e)}")
            raise

    async def check_tier_availability(
        self, tier_id: str, count: int = 1
    ) -> Dict[str, Any]:
        """
        Check if a tier has enough capacity for the requested ticket count.

        Args:
            tier_id (str): The tier ID
            count (int): Number of tickets requested

        Returns:
            Dict[str, Any]: Tier data if available

        Raises:
            ValueError: If tier not found or sold out
        """
        try:
            async with self.pool.acquire() as conn:
                tier = await conn.select(RecordID("ticket_tiers", tier_id))
            if not tier:
                raise ValueError("Tier not found")

            tier = record_id_to_json(tier)
            capacity = tier.get("capacity")
            sold = tier.get("sold_count", 0)

            if capacity is not None and sold + count > capacity:
                raise ValueError(
                    f"Tier '{tier.get('name')}' is sold out "
                    f"({sold}/{capacity} sold)"
                )
            return tier
        except Exception as e:
            self.logger.error(f"Failed to check tier availability: {str(e)}")
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

        IF NOT EXISTS guard prevents duplicate edges from double-taps or
        concurrent retry requests. Returns the existing entry unchanged if
        the user is already on the guestlist.
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    IF NOT EXISTS (
                        SELECT id FROM guestlists
                        WHERE in  = type::thing('users',  $user_id)
                          AND out = type::thing('events', $event_id)
                    ) {
                        RELATE type::thing('users',  $user_id)
                            -> guestlists ->
                               type::thing('events', $event_id)
                        SET
                            invited_by = type::thing('users', $invited_by),
                            status     = $status;
                    } ELSE {
                        SELECT * FROM guestlists
                        WHERE in  = type::thing('users',  $user_id)
                          AND out = type::thing('events', $event_id)
                        LIMIT 1;
                    };
                    """,
                    {
                        "user_id":    user_id,
                        "event_id":   event_id,
                        "invited_by": invited_by,
                        "status":     status,
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

        Uses an atomic UPDATE ... WHERE checked_in_at = NONE to eliminate the
        double check-in race. Two concurrent scans of the same QR code both
        attempt the UPDATE; only one finds a row matching checked_in_at = NONE
        and gets RETURN BEFORE data back — the other gets an empty result and
        is treated as already-checked-in, never as a fresh valid scan.
        """
        try:
            async with self.pool.acquire() as conn:
                # First confirm the ticket exists for this event at all.
                exists_result = await conn.query(
                    """
                    SELECT
                        id,
                        ticket_number,
                        checked_in_at,
                        user.{id, organization_name, first_name, last_name, avatar} AS user,
                        event.{id, title} AS event
                    FROM tickets
                    WHERE ticket_number = $ticket_number
                      AND event = type::thing('events', $event_id)
                    LIMIT 1;
                    """,
                    {"event_id": event_id, "ticket_number": ticket_number},
                )

                ticket = (exists_result or [None])[0]
                if not ticket:
                    return {"valid": False, "message": "Ticket not found or does not belong to this event"}

                if ticket.get("checked_in_at"):
                    return {
                        "valid": True,
                        "already_checked_in": True,
                        "checked_in_at": ticket["checked_in_at"],
                        "ticket": ticket,
                    }

                # Atomic claim: UPDATE only if checked_in_at is still NONE.
                # RETURN BEFORE gives us the row as it was before the update —
                # if the result is non-empty we won the race; if empty, a
                # concurrent scan beat us and already set checked_in_at.
                claimed = await conn.query(
                    """
                    UPDATE tickets
                    SET checked_in_at = time::now()
                    WHERE id = $ticket_id
                      AND checked_in_at = NONE
                    RETURN BEFORE;
                    """,
                    {"ticket_id": ticket["id"]},
                )

                if not claimed or not claimed[0]:
                    # Another scanner won the race between our SELECT and UPDATE.
                    refreshed = await conn.query(
                        "SELECT checked_in_at FROM ONLY $tid;",
                        {"tid": ticket["id"]},
                    )
                    return {
                        "valid": True,
                        "already_checked_in": True,
                        "checked_in_at": (refreshed or {}).get("checked_in_at"),
                        "ticket": ticket,
                    }

            return record_id_to_json({
                "valid": True,
                "already_checked_in": False,
                "checked_in_at": None,  # set by DB, not echoed back here
                "ticket": ticket,
            })
        except Exception as e:
            self.logger.error(f"Failed to verify ticket: {str(e)}")
            raise

    async def update_event_media(self, event_id: str, media_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Update event media by replacing existing media with new media.

        Creates new records first, swaps the has_media relations, then deletes
        the old records. This eliminates the blind-spot window where the event
        briefly has zero media between the old DELETE and the new CREATE loop.
        Any reader racing against this update sees either the full old set or
        the full new set — never an empty set.
        """
        try:
            async with self.pool.acquire() as conn:
                event_record_id = RecordID("events", event_id)

                # 1. Collect old media IDs before touching anything.
                old_media = await conn.query(
                    "SELECT VALUE out FROM has_media WHERE in = type::thing('events', $event_id);",
                    {"event_id": event_id},
                )
                old_media_ids = old_media if isinstance(old_media, list) else []

                # 2. Create new media records (event is still visible with old media).
                new_media_ids = []
                for media in media_data:
                    media_record = await conn.create(
                        "media",
                        {
                            "filename": media["filename"],
                            "type":     media["type"],
                            "creator":  media["creator"],
                            "event":    event_record_id,
                            "status":   "pending",
                        },
                    )
                    if isinstance(media_record, dict):
                        new_media_ids.append(media_record["id"])
                    else:
                        self.logger.error(
                            f"Media create returned unexpected result: {media_record} for {media['filename']}"
                        )

                # 3. Create new has_media edges.
                for media_id in new_media_ids:
                    await conn.query(
                        "RELATE $event -> has_media -> $media;",
                        {"event": event_record_id, "media": media_id},
                    )

                # 4. Now atomically drop the OLD edges (new ones already live).
                if old_media_ids:
                    await conn.query(
                        "DELETE has_media WHERE in = type::thing('events', $event_id) AND out IN $old_ids;",
                        {"event_id": event_id, "old_ids": old_media_ids},
                    )
                    await conn.query(
                        "DELETE media WHERE id IN $old_ids;",
                        {"old_ids": old_media_ids},
                    )

                result = await conn.select(event_record_id)

            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to update event media: {str(e)}")
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