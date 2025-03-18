from quart import Quart
from surrealdb import AsyncSurreal, RecordID
import os
from typing import Optional
from shared.utils import record_id_to_json

import json
import logging

# Get the logger
logger = logging.getLogger(__name__)


class UsersDB:
    def __init__(self, db: AsyncSurreal) -> None:
        self.db: AsyncSurreal = db

    async def close(self):
        self.db.close()

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

        await self.db.let("origin", RecordID("users", origin_id))
        query = f"""
        SELECT 
            {', '.join(select_fields)}
        FROM ONLY $origin;
        """

        result = await self.db.query(query)
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
        await self.db.let("origin", RecordID("users", data["origin_id"]))
        await self.db.let("target", RecordID("users", data["target_id"]))

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
        await self.db.query(
            query,
            {
                "status": data.get("status", "pending"),
            },
        )
        # Get the new relationship
        result = await self.db.query(
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
        await self.db.let("edge", RecordID("friends", connection_id))
        query = """
            UPDATE ONLY $edge SET status = $status
        """
        result = await self.db.query(query, {"status": data.get("status", "pending")})
        return record_id_to_json(result)

    async def delete_connection(self, connection_id: str):
        """
        Delete the connection between two users

        Args:
            connection_id (str, required): The ID of the connection
        Returns:
            dict: The deleted relationship details
        """
        await self.db.let("edge", RecordID("friends", connection_id))
        query = """
            DELETE ONLY $edge
        """
        result = await self.db.query(query)
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
        result = await self.db.query(
            """
            SELECT
                *
            FROM ONLY type::thing('users', $id);
            """,
            {"id": id},
        )
        logger.info(json.dumps(result, indent=4, default=str))
        return record_id_to_json(result)

    async def delete(self, id: str) -> Optional[dict]:
        """
        Delete a user by ID

        Args:
            id (str): The user ID to delete

        Returns:
            Optional[dict]: Deleted user data or None if not found
        """
        result = await self.db.delete(RecordID("users", id))
        return result

    async def update(self, data: dict) -> dict:
        """
        Update user data

        Args:
            data (dict): User data to update, must include 'id' field

        Returns:
            dict: Updated user data
        """
        result = await self.db.query(
            "UPDATE ONLY type::thing('users', $record_id) MERGE $content RETURN AFTER;",
            {"content": data, "record_id": data["id"]},
        )
        logger.info(json.dumps(result, indent=4, default=str))
        return record_id_to_json(result)


async def init_db(app: Quart) -> UsersDB:
    """
    Initialize database connection

    Args:
        app (Quart): Quart application instance

    Returns:
        UsersDB: Database connection manager
    """
    db = AsyncSurreal(os.getenv("SURREAL_URI"))

    await db.signin(
        {"username": os.getenv("SURREAL_USER"), "password": os.getenv("SURREAL_PASS")}
    )
    await db.use("partyscene", "partyscene")
    return UsersDB(db)
