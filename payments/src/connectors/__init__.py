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

        IF NOT EXISTS guard prevents duplicate edges when the webhook fires
        more than once for the same payment (Stripe/Paystack retry behaviour).
        """
        try:
            user_id  = data["user"]
            event_id = data["event"]
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    IF NOT EXISTS (
                        SELECT id FROM attends
                        WHERE in  = type::thing('users',  $user_id)
                          AND out = type::thing('events', $event_id)
                    ) {
                        RELATE type::thing('users',  $user_id)
                            -> attends ->
                               type::thing('events', $event_id)
                        SET status = $status;
                    };
                    """,
                    {"user_id": user_id, "event_id": event_id, "status": data["status"]},
                )
            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to create attendance: {str(e)}")
            raise

    async def _create_ticket(self, data):
        """
        Create a ticket in the database.

        Args:
            data (dict): The ticket data to create
                - event (str): Event ID (required)
                - user (str): User ID (optional, for authenticated users)
                - guest_email (str): Email (optional, for guest purchases)
                - tier (str): Tier ID (optional)

        Returns:
            dict: The created ticket object
        """
        if "user" in data and data["user"]:
            data["user"] = RecordID("users", data.pop("user"))
        elif "user" in data:
            data.pop("user")
        
        data["event"] = RecordID("events", data.pop("event"))

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

    async def check_tier_availability(
        self, tier_id: str, count: int = 1
    ) -> Dict[str, Any]:
        """
        Check if a tier has enough capacity for the requested ticket count.

        Reads capacity and sold_count in a single SELECT so the values are
        consistent. Actual sold_count enforcement happens at ticket creation
        time via increment_tier_sold_count — this check is a fast pre-flight
        that gives a clean error message before hitting Stripe/Paystack.
        """
        try:
            async with self.pool.acquire() as conn:
                tier = (await conn.select(RecordID("ticket_tiers", tier_id)))[0]
            if not tier:
                raise ValueError("Tier not found")

            tier = record_id_to_json(tier)
            capacity = tier.get("capacity")
            sold = tier.get("sold_count", 0)

            if capacity is not None and (sold + count) > capacity:
                raise ValueError(
                    f"Tier '{tier.get('name')}' is sold out "
                    f"({sold}/{capacity} sold)"
                )
            return tier
        except Exception as e:
            self.logger.error(f"Failed to check tier availability: {str(e)}")
            raise

    async def _get_events_count(self) -> int:
        """
        Get the total number of events.

        Returns:
            int: The total number of events
        """
        try:
            async with self.pool.acquire() as conn:
                # Use SELECT id to avoid duration CBOR bug in count subquery
                result = await conn.query(
                    """
                    RETURN count((SELECT id FROM events));
                    """
                )
            self.logger.debug(json.dumps(result, option=json.OPT_INDENT_2, default=str))
            return result if result else 0
        except Exception as e:
            self.logger.error(f"Failed to fetch events count: {str(e)}")
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

    async def update_paystack_subaccount(self, user_id: str, subaccount_code: str) -> Dict[str, Any]:
        """
        Update user's Paystack subaccount ID.

        Args:
            user_id (str): The user ID
            subaccount_code (str): Paystack subaccount code

        Returns:
            Dict[str, Any]: Updated user data
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    "UPDATE ONLY type::thing('users', $user_id) SET paystack_subaccount_id = $subaccount_code RETURN AFTER;",
                    {"user_id": user_id, "subaccount_code": subaccount_code},
                )
            self.logger.info(f"Updated Paystack subaccount for user {user_id}: {subaccount_code}")
            return record_id_to_json(result)
        except Exception as e:
            self.logger.error(f"Failed to update Paystack subaccount: {str(e)}")
            raise

    async def get_user_paystack_subaccount(self, user_id: str) -> Optional[str]:
        """
        Get user's Paystack subaccount ID.

        Args:
            user_id (str): The user ID

        Returns:
            Optional[str]: Paystack subaccount code or None
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    "SELECT VALUE paystack_subaccount_id FROM type::thing('users', $user_id);",
                    {"user_id": user_id},
                )
            if result and result[0]:
                return result[0]
            return None
        except Exception as e:
            self.logger.error(f"Failed to get Paystack subaccount: {str(e)}")
            raise

    async def _get_ticket_details_by_email(self, email: str, event_id: str) -> list:
        """
        Get ticket details for an email and event (for guest purchases).

        Args:
            email (str): The guest email
            event_id (str): The event ID

        Returns:
            list: Ticket details including ticket number, event info
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    SELECT 
                        ticket_number,
                        guest_email,
                        guest_name,
                        tier.{name, price} AS tier,
                        event.id,
                        event.title,
                        event.description,
                        event.time,
                        event.location,
                        event.duration,
                        event.price,
                        event.host.{organization_name, first_name, last_name} AS organizer,
                        created_at
                    FROM tickets 
                    WHERE guest_email = $email 
                    AND event = type::thing('events', $event_id)
                    ORDER BY created_at DESC;
                    """,
                    {"email": email, "event_id": event_id}
                )
            return record_id_to_json(result) if result else []
        except Exception as e:
            self.logger.error(f"Failed to get ticket details: {str(e)}")
            raise

    async def _get_ticket_details_by_user(self, user_id: str, event_id: str) -> list:
        """
        Get ticket details for a user and event (for authenticated purchases).

        Args:
            user_id (str): The user ID
            event_id (str): The event ID

        Returns:
            list: Ticket details including ticket number, event info
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """
                    SELECT 
                        ticket_number,
                        tier.{name, price} AS tier,
                        event.id,
                        event.title,
                        event.description,
                        event.time,
                        event.location,
                        event.duration,
                        event.price,
                        event.host.{organization_name, first_name, last_name} AS organizer,
                        user.email,
                        user.first_name,
                        user.last_name
                    FROM tickets 
                    WHERE user = type::thing('users', $user_id) 
                    AND event = type::thing('events', $event_id)
                    ORDER BY created_at DESC;
                    """,
                    {"user_id": user_id, "event_id": event_id}
                )
            return record_id_to_json(result) if result else []
        except Exception as e:
            self.logger.error(f"Failed to get ticket details: {str(e)}")
            raise

    async def increment_tier_sold_count(self, tier_id: str, count: int = 1) -> None:
        """
        Atomically increment sold_count on a ticket tier after confirmed purchase.

        Using += in SurrealDB is an atomic read-modify-write at the DB level,
        so concurrent webhook deliveries for different purchases accumulate
        correctly without a SELECT/UPDATE race.
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.query(
                    "UPDATE type::thing('ticket_tiers', $tier_id) SET sold_count += $count;",
                    {"tier_id": tier_id, "count": count},
                )
            self.logger.info(f"Incremented sold_count by {count} for tier {tier_id}")
        except Exception as e:
            self.logger.error(f"Failed to increment tier sold_count: {str(e)}")
            raise

    async def increment_attendee_count(self, event_id: str, count: int = 1) -> None:
        """
        Increment the attendee_count for an event.

        Args:
            event_id (str): The event ID
            count (int): Number to increment by (default 1)
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.query(
                    "UPDATE type::thing('events', $event_id) SET attendee_count += $count;",
                    {"event_id": event_id, "count": count}
                )
            self.logger.info(f"Incremented attendee_count by {count} for event {event_id}")
        except Exception as e:
            self.logger.error(f"Failed to increment attendee_count: {str(e)}")
            raise

    async def assign_collector(
        self, event_id: str, collector_id: str, host_id: str
    ) -> dict:
        """
        Designate a user as a tap-to-pay collector for an event.

        Verifies atomically that the caller is the event host before
        creating the edge. Raises ValueError if the event is not found,
        the caller is not the host, or the collector is already assigned.

        Args:
            event_id:     Event to assign the collector to.
            collector_id: User being designated as collector.
            host_id:      JWT identity of the requesting user (must be host).

        Returns:
            The created event_collectors edge as a plain dict.
        """
        async with self.pool.acquire() as conn:
            await conn.let("event", RecordID("events", event_id))
            await conn.let("host",  RecordID("users",  host_id))
            await conn.let("coll",  RecordID("users",  collector_id))

            response = await conn.query_raw(
                """
                LET $ev = SELECT host, status FROM ONLY $event;
                IF $ev = NONE {
                    THROW "event_not_found";
                };
                IF $ev.host != $host {
                    THROW "not_host";
                };
                IF $host = $coll {
                    THROW "self_assign";
                };
                IF $ev.status IN ["ended", "cancelled"] {
                    THROW "event_inactive";
                };
                RELATE ONLY $event -> event_collectors -> $coll
                    SET assigned_by = $host
                    RETURN AFTER;
                """
            )

        stmts = response.get("result", [])
        for s in stmts:
            if isinstance(s, dict) and s.get("status") == "ERR":
                err = s.get("result", "")
                if "event_not_found" in err:
                    raise ValueError("Event not found")
                if "not_host" in err:
                    raise ValueError("Only the event host can assign collectors")
                if "self_assign" in err:
                    raise ValueError("Host cannot assign themselves as a collector")
                if "event_inactive" in err:
                    raise ValueError("Cannot assign collectors to an ended or cancelled event")
                raise Exception(f"assign_collector failed: {err}")

        edge = stmts[-1]["result"]
        if not edge:
            raise ValueError("Collector already assigned to this event")
        result = edge[0] if isinstance(edge, list) else edge
        return record_id_to_json(result)

    async def remove_collector(
        self, event_id: str, collector_id: str, host_id: str
    ) -> bool:
        """
        Remove a collector assignment for an event.

        Verifies the caller is the host before deleting. Returns True
        if the edge existed and was removed, False if it was not found.
        """
        async with self.pool.acquire() as conn:
            await conn.let("event", RecordID("events", event_id))
            await conn.let("host",  RecordID("users",  host_id))
            await conn.let("coll",  RecordID("users",  collector_id))

            response = await conn.query_raw(
                """
                LET $ev = SELECT host FROM ONLY $event;
                IF $ev = NONE {
                    THROW "event_not_found";
                };
                IF $ev.host != $host {
                    THROW "not_host";
                };
                DELETE event_collectors
                    WHERE in = $event AND out = $coll
                    RETURN BEFORE;
                """
            )

        stmts = response.get("result", [])
        for s in stmts:
            if isinstance(s, dict) and s.get("status") == "ERR":
                err = s.get("result", "")
                if "event_not_found" in err:
                    raise ValueError("Event not found")
                if "not_host" in err:
                    raise ValueError("Only the event host can remove collectors")
                raise Exception(f"remove_collector failed: {err}")

        deleted = stmts[-1].get("result", [])
        return bool(deleted)

    async def list_collectors(self, event_id: str) -> list:
        """
        Return all collectors assigned to an event with basic profile info.
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                SELECT
                    out.{id, first_name, last_name, username, avatar} AS user,
                    assigned_by.{id, first_name, last_name} AS assigned_by,
                    created_at
                FROM event_collectors
                WHERE in = type::thing('events', $event_id);
                """,
                {"event_id": event_id},
            )
        return record_id_to_json(result) if result else []

    async def check_terminal_authorization(
        self, event_id: str, user_id: str
    ) -> tuple[bool, str]:
        """
        Check if a user is authorized to collect tap-to-pay payments for
        an event. Returns (authorized, host_stripe_account_id).

        A user is authorized if they are the host OR an assigned collector.
        The host's stripe_account_id is always returned so the caller can
        create a properly scoped connection token and payment intent.
        """
        async with self.pool.acquire() as conn:
            await conn.let("event", RecordID("events", event_id))
            await conn.let("user",  RecordID("users",  user_id))

            response = await conn.query_raw(
                """
                LET $ev = SELECT host, host.stripe_account_id AS stripe_id
                    FROM ONLY $event;
                IF $ev = NONE {
                    THROW "event_not_found";
                };
                LET $is_host = $ev.host = $user;
                LET $is_collector = count(
                    SELECT id FROM event_collectors
                    WHERE in = $event AND out = $user
                ) > 0;
                RETURN {
                    authorized:       $is_host OR $is_collector,
                    stripe_account_id: $ev.stripe_id
                };
                """
            )

        stmts = response.get("result", [])
        for s in stmts:
            if isinstance(s, dict) and s.get("status") == "ERR":
                err = s.get("result", "")
                if "event_not_found" in err:
                    raise ValueError("Event not found")
                raise Exception(f"check_terminal_authorization failed: {err}")

        payload = stmts[-1]["result"]
        return payload["authorized"], payload.get("stripe_account_id", "")


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
        min_connections=3,
        max_connections=20,  # Increased from 10 to handle more concurrent requests
        max_idle_time=60,  # Reduced - recycle idle connections faster
        connection_timeout=10.0,  # Increased from 5s to allow slower connection establishment
        acquisition_timeout=30.0,  # Increased from 10s to 30s to prevent premature cancellation
        health_check_interval=10,  # Reduced - check health more frequently
        max_usage_count=100,  # Reduced - recycle connections more aggressively
        connection_retry_attempts=3,
        connection_retry_delay=1.0,
        schema_file=SCHEMA_FILE,
        reset_on_return=True,
        log_queries=True,
    )

    # Create PaymentsDB instance
    payments_db = PaymentsDB(pool, app.logger)

    return payments_db, pool_manager