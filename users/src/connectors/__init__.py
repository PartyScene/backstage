from quart import Quart
from surrealdb import AsyncSurreal, RecordID
import os
from typing import Optional, Tuple, Any
from shared.utils import record_id_to_json
from purreal import SurrealDBConnectionPool, SurrealDBPoolManager


import orjson as json


class UsersDB:
    def __init__(self, pool: SurrealDBConnectionPool, logger) -> None:
        self.pool = pool
        self.logger = logger

    async def _report_resource(self, data: dict):
        """
        Report this resource which is a user
        Args:
            data (dict): The data to report
        """
        data["reporter"] = RecordID("users", data["reporter"])
        data["resource"] = RecordID("users", data["resource"])
        async with self.pool.acquire() as conn:
            result = await conn.create("reports", data)
            return record_id_to_json(result)

    async def _info(self):
        """Get database information."""
        return await self.pool.execute_query("INFO FOR DB")

    async def get_connections_at_degree(self, origin_id: str, max_degree: int = 3):
        """
        Find all connections up to N degrees of separation

        Args:
            origin_id (str): The ID of the origin user
            max_degree (int): Maximum degree of separation (default: 3)

        Returns:
            dict: Contains connections at different degrees
        """
        if max_degree < 1 or max_degree > 6:
            return {"error": "Degree must be between 1 and 6"}

        async with self.pool.acquire() as conn:

            result = await conn.query(
                "RETURN fn::get_friends($origin);",
                {"origin": RecordID("users", origin_id)},
            )
        return record_id_to_json(result)
    
    async def fetch_user_tickets(self, user_id: Any, page: int = 1, limit: int = 50):
        """
        Fetch tickets bought by this user

        Args:
            user_id (str, required): The origin user ID
            page (int, optional): The page number (default: 1)
            limit (int, optional): The number of tickets per page (default: 50)
        Returns:
            list: The created relationship details
        """

        async with self.pool.acquire() as conn:

            result = await conn.query(
                "RETURN fn::fetch_user_tickets($origin, $page, $limit);",
                {
                    "origin": RecordID("users", user_id),
                    "page": page,
                    "limit": limit,
                },
            )
        return record_id_to_json(result)

    async def fetch_user_events(self, user_id: Any, created: bool = False):
        """
        Fetch events attended by this user

        Args:
            user_id (str, required): The origin user ID
        Returns:
            list: The created relationship details
        """
        if created:
            # Execute both queries concurrently with separate connections to avoid timeout
            import asyncio
            
            async def fetch_attended():
                async with self.pool.acquire() as conn:
                    return await conn.query(
                        "RETURN fn::fetch_attended_events($origin);",
                        {"origin": RecordID("users", user_id)},
                    )
            
            async def fetch_created():
                async with self.pool.acquire() as conn:
                    return await conn.query(
                        "RETURN fn::fetch_created_events($origin);",
                        {"origin": RecordID("users", user_id)},
                    )
            
            # Execute both queries in parallel
            attended_result, created_result = await asyncio.gather(
                fetch_attended(), fetch_created()
            )
            result = {"attended": attended_result, "created": created_result}
        else:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    "RETURN fn::fetch_attended_events($origin);",
                    {"origin": RecordID("users", user_id)},
                )

        return record_id_to_json(result)

    async def create_friend_relationship(self, data: dict):
        """
        Create a bidirectional friend relationship between two users.

        Args:
            data (dict, required): The friend relationship data containing:
                - origin: The ID of the first user
                - target: The ID of the second user
                - status: Optional relationship status ('pending', 'accepted', 'blocked')
        Returns:
            dict: The created relationship details
        """
        # First check if relationship already exists
        async with self.pool.acquire() as conn:

            result = await conn.query(
                "RETURN fn::create_relationship($origin, $target, $status);",
                {
                    "origin": RecordID("users", data["origin_id"]),
                    "target": RecordID("users", data["target_id"]),
                    "status": data.get("status", "pending"),
                },
            )

        return record_id_to_json(result["relationship"])

    async def update_friend_relationship(self, connection_id: str, data: dict):
        """
        Update the connection status between two users

        Args:
            connection_id (str, required): The ID of the connection
            data (dict, required): The friend relationship data containing:
                - origin: The ID of the first user
                - target: The ID of the second user
                - status: Optional relationship status ('pending', 'accepted', 'blocked', 'removed', 'rejected')
        Returns:
            dict: The updated relationship details
        """
        async with self.pool.acquire() as conn:
            await conn.let("edge", RecordID("friends", connection_id))
            query = """
                    UPDATE ONLY $edge SET status = $status
                """
            result = await conn.query(query, {"status": data.get("status", "pending")})
        return record_id_to_json(result)

    async def delete_connection(self, connection_id: str):
        """
        Delete the connection between two users

        Args:
            connection_id (str, required): The ID of the connection
        Returns:
            dict: The deleted relationship details
        """
        async with self.pool.acquire() as conn:
            await conn.let("edge", RecordID("friends", connection_id))
            query = """
                DELETE ONLY $edge
            """
            result = await conn.query(query)
        return record_id_to_json(result)

    async def block_user(self, blocker_id: str, blocked_id: str):
        """
        Create a block relationship between two users (unidirectional).
        blocker_id blocks blocked_id.

        Args:
            blocker_id (str): The ID of the user who is blocking
            blocked_id (str): The ID of the user being blocked

        Returns:
            dict: The created block relationship
        """
        async with self.pool.acquire() as conn:
            # Check if block relationship already exists
            existing = await conn.query(
                """
                SELECT * FROM blocks WHERE in = $blocker 
                AND out = $blocked
                """,
                {"blocker": RecordID("users", blocker_id), "blocked": RecordID("users", blocked_id)}
            )
            
            if existing:
                return record_id_to_json(existing[0])
            
            # Create block relationship
            result = await conn.query(
                """
                RELATE ONLY $blocker -> blocks -> $blocked
                SET created_at = time::now()
                """,
                {"blocker": RecordID("users", blocker_id), "blocked": RecordID("users", blocked_id)}
            )
            
        return record_id_to_json(result)

    async def unblock_user(self, blocker_id: str, blocked_id: str):
        """
        Remove a block relationship between two users.

        Args:
            blocker_id (str): The ID of the user who is unblocking
            blocked_id (str): The ID of the user being unblocked

        Returns:
            dict: The deleted block relationship or None if not found
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                DELETE blocks WHERE in = $blocker 
                AND out = $blocked
                RETURN BEFORE
                """,
                {"blocker": RecordID("users", blocker_id), "blocked": RecordID("users", blocked_id)}
            )
            
        return record_id_to_json(result) if result else None

    async def get_blocked_users(self, user_id: str):
        """
        Fetch all users blocked by a specific user.

        Args:
            user_id (str): The ID of the user who is blocking.

        Returns:
            list: A list of blocked user objects.
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                SELECT ->blocks->users as blocked FROM $user
                """,
                {"user": RecordID("users", user_id)}
            )
            if result and len(result) > 0 and 'blocked' in result[0] and result[0]['blocked']:
                return record_id_to_json(result[0]['blocked'])
        return []

    async def fetch(self, id: str) -> Optional[dict]:
        """
        Fetch one user by ID

        Args:
            id (str): The user ID to fetch

        Returns:
            Optional[dict]: User data including attended events, or None if not found
        """  # ->attends->events[WHERE true] AS scenes,
        # ->friends
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                SELECT
                    * OMIT password
                FROM ONLY type::thing('users', $id);
            """,
                {"id": id},
            )
        self.logger.info(json.dumps(result, option=json.OPT_INDENT_2, default=str))
        return record_id_to_json(result)

    async def delete(self, id: str) -> Optional[dict]:
        """
        Delete a user by ID

        Args:
            id (str): The user ID to delete

        Returns:
            Optional[dict]: Deleted user data or None if not found
        """
        async with self.pool.acquire() as conn:
            result = await conn.delete(RecordID("users", id))
        return result

    def subset(self, d, keys):
        return {k: d[k] for k in keys if k in d}

    async def update(self, data: dict) -> dict:
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

                # if isinstance(media_query_result, dict):
                #     data["avatar"] = media_query_result["id"]
        
        data.pop("type", None)
        
        async with self.pool.acquire() as conn:
            result = await conn.query(
                "UPDATE ONLY type::thing('users', $record_id) MERGE $content RETURN AFTER;",
                {"content": data, "record_id": data["id"]},
            )
        self.logger.info(json.dumps(result, option=json.OPT_INDENT_2, default=str))
        return record_id_to_json(result)


async def init_db(app) -> Tuple[UsersDB, SurrealDBConnectionPool]:
    """
    Initialize the database connection pool and return an UsersDB instance.

    Args:
        app: The Quart application instance

    Returns:
        Tuple[UsersDB, SurrealDBConnectionPool]: Initialized database connector and connection pool
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
        name="users_pool",
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

    # Create UsersDB instance
    users_db = UsersDB(pool, app.logger)

    return users_db, pool_manager
