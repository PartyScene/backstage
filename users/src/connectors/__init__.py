from quart import Quart
from surrealdb import AsyncSurreal, RecordID
import os
from typing import Optional, Tuple
from shared.utils import record_id_to_json
from purreal import SurrealDBConnectionPool, SurrealDBPoolManager

import json


class UsersDB:
    def __init__(self, pool: SurrealDBConnectionPool, logger) -> None:
        self.pool = pool
        self.logger = logger

    async def _info(self):
        """Get database information."""
        return await self.pool.execute_query("INFO FOR DB")

    async def find_connections_at_degree(self, origin_id: str, max_degree: int = 3):
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

        # Build the SELECT fields dynamically based on max_degree
        select_fields = []
        for i in range(1, max_degree + 1):
            path = "->friends->users" * i
            select_fields.append(f"{path}.* AS degree_{i}")

        async with self.pool.acquire() as conn:
            await conn.let("origin", RecordID("users", origin_id))
            query = f"""
            SELECT 
                {', '.join(select_fields)}
            FROM ONLY $origin;
            """
            result = await conn.query(query)
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
            await conn.let("origin", RecordID("users", data["origin_id"]))
            await conn.let("target", RecordID("users", data["target_id"]))

        query = """
            -- Check existing relationship
            LET $existing = (
                SELECT VALUE <->friends.* FROM $origin
                WHERE <->friends[WHERE out = $target OR in = $target]
            );
            
            -- Create new relationship if none exists
            LET $new = IF(array::len($existing) == 0) THEN (
                -- Create bidirectional relationship
                RELATE ONLY $origin -> friends -> $target SET
                    status = $status,
                    created_at = time::now()
            ) ELSE $existing
            END;
            
            RETURN {
                relationship: $new,
                is_new: array::len($existing) == 0
            };
        """
        # Execute the query
        async with self.pool.acquire() as conn:
            result = await conn.query(
                query,
                {
                    "status": data.get("status", "pending"),
                },
            )
        # Get the new relationship
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                SELECT VALUE <->friends.* FROM $origin
                WHERE <->friends[WHERE out = $target OR in = $target]
                """
            )
        return record_id_to_json(result)[0]

    async def update_friend_relationship(self, connection_id: str, data: dict):
        """
        Update the connection status between two users

        Args:
            connection_id (str, required): The ID of the connection
            data (dict, required): The friend relationship data containing:
                - origin: The ID of the first user
                - target: The ID of the second user
                - status: Optional relationship status ('pending', 'accepted', 'blocked')
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
                    *
                FROM ONLY type::thing('users', $id);
            """,
                {"id": id},
            )
        self.logger.info(json.dumps(result, indent=4, default=str))
        result.pop("password")
        result.pop("bio")
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
                data["creator"] = RecordID("users", data["creator"])
                media_query_result = await conn.create(
                    "media", self.subset(data, ["filename", "type", "creator"])
                )
                self.logger.warning(
                    json.dumps(media_query_result, indent=4, default=str)
                )

                avatar_media = RecordID(
                    "media", record_id_to_json(media_query_result)["id"]
                )

                data["avatar"] = avatar_media

        async with self.pool.acquire() as conn:
            result = await conn.query(
                "UPDATE ONLY type::thing('users', $record_id) MERGE $content RETURN AFTER;",
                {"content": data, "record_id": data["id"]},
            )
        self.logger.info(json.dumps(result, indent=4, default=str))
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
