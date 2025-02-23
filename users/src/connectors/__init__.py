from quart import Quart
from surrealdb import AsyncSurreal, RecordID
import os
from typing import Optional


class Users:
    def __init__(self, db: AsyncSurreal) -> None:
        self.db : AsyncSurreal = db

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
            select_fields.append(f"{path}.first_name AS degree_{i}")

        await self.db.let('origin', RecordID('users', origin_id))
        query = f"""
        SELECT 
            {', '.join(select_fields)}
        FROM $origin;
        """
        
        result = await self.db.query(query)
        return result[0]["result"][0] if result[0]["result"] else {}

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
        query = """
            LET $origin = type::thing('users', $origin);
            LET $target = type::thing('users', $target);
            
            -- Check existing relationship
            LET $existing = (
                SELECT * FROM friends 
                WHERE 
                    (in = $origin AND out = $target)
                    OR (in = $target AND out = $origin)
            );
            
            -- Create new relationship if none exists
            LET $new = IF(array::len($existing) == 0) THEN (
                -- Create bidirectional relationship
                RELATE $origin -> friends -> $target SET
                    status = $status,
                    created_at = time::now()
            ) ELSE $existing;
            
            RETURN {
                relationship: $new,
                is_new: array::len($existing) == 0
            };
        """
        
        result = await self.db.query(
            query,
            {
                "origin": data["origin"],
                "target": data["target"],
                "status": data.get("status", "pending")
            }
        )
        return result[0]["result"][0]
    
    async def update_friend_relationship(self, data: dict):
        """
        Update the connection status between two users
        
        Args:
            data (dict, required): The friend relationship data containing:
                - origin: The ID of the first user
                - target: The ID of the second user
                - status: Optional relationship status ('pending', 'accepted', 'blocked')
        Returns:
            dict: The updated relationship details
        """
        await self.db.let('edge', RecordID('friends', data["id"]))
        query = """
            UPDATE $edge SET status = $status
        """
        result = await self.db.query(
            query,
            {
                "status": data.get("status", "pending")
            }
        )
        return result[0]["result"][0]

    async def fetch(self, id: str) -> Optional[dict]:
        """
        Fetch one user by ID
        
        Args:
            id (str): The user ID to fetch
            
        Returns:
            Optional[dict]: User data including attended events, or None if not found
        """
        result = await self.db.query(
            """
            SELECT 
                *,
                ->attends->events[WHERE true] AS scenes,
                ->friends->users[WHERE true] AS friends
            FROM users 
            WHERE id = type::thing('users', $id);
            """,
            {"id": id},
        )
        return result[0]["result"][0] if result[0]["result"] else None

    async def delete(self, id: str) -> Optional[dict]:
        """
        Delete a user by ID
        
        Args:
            id (str): The user ID to delete
            
        Returns:
            Optional[dict]: Deleted user data or None if not found
        """
        result = await self.db.delete(RecordID('users', id))
        return result[0]["result"][0]

    async def update(self, data: dict) -> dict:
        """
        Update user data
        
        Args:
            data (dict): User data to update, must include 'id' field
            
        Returns:
            dict: Updated user data
        """
        result = await self.db.query(
            "UPDATE type::thing('users', $record_id) MERGE $content",
            {"content": data, "record_id": data["id"]},
        )
        return result[0]["result"][0]


class UsersDB:
    def __init__(self, db: AsyncSurreal) -> None:
        self.db = db
        self.users = Users(db)


async def init_db(app: Quart) -> UsersDB:
    """
    Initialize database connection
    
    Args:
        app (Quart): Quart application instance
        
    Returns:
        UsersDB: Database connection manager
    """
    db = AsyncSurreal(app.config["SURREAL_URI"])
    await db.connect()

    await db.signin(
        {
            "username": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD")
        }
    )
    await db.use("partyscene", "partyscene")
    return UsersDB(db)
