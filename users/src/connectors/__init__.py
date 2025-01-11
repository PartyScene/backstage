from quart import Quart
from surrealdb import AsyncSurrealDB
import os
from typing import Optional


class Users:
    def __init__(self, db: AsyncSurrealDB) -> None:
        self.db = db

    async def find_connections_at_degree(self, origin_id: str, degree: int = 1):
        """
        Find all users connected to the origin user at exactly N degrees of separation.
        
        Args:
            origin_id (str): The ID of the origin user
            degree (int): The exact degree of separation (1-6) to search for
        
        Returns:
            dict: Contains connections at that degree and total count
        """
        if degree < 1 or degree > 6:
            return {"error": "Degree must be between 1 and 6"}

        # Build the path pattern based on degree
        path = "->friends->users" * degree
        
        # For degree > 1, we need to exclude connections from lower degrees
        exclusion_paths = []
        if degree > 1:
            for i in range(1, degree):
                exclusion_paths.append(f"SELECT {('->friends->users' * i)} as users FROM $origin")

        query = f"""
        LET $origin = type::thing('users', $origin);
        
        SELECT 
            {path} as connections,
            count({path}) as total,
            array::group(connections) as grouped_by_degree
        FROM $origin
        WHERE connections != $origin
        {f"AND connections NOT IN ({' UNION '.join(exclusion_paths)})" if exclusion_paths else ""}
        GROUP BY connections;
        """
        
        result = await self.db.query(query, {"origin": origin_id})
        return result[0]["result"]

    async def find_shortest_path(self, origin_id: str, target_id: str, max_degree: int = 6):
        """
        Find the shortest path between two users up to max_degree of separation.
        
        Args:
            origin_id (str): The ID of the starting user
            target_id (str): The ID of the target user
            max_degree (int): Maximum degrees of separation to check (default: 6)
        
        Returns:
            dict: Contains the path found, its length, and the users involved
        """
        if max_degree < 1 or max_degree > 6:
            return {"error": "Max degree must be between 1 and 6"}

        query = """
        LET $origin = type::thing('users', $origin);
        LET $target = type::thing('users', $target);
        
        SELECT 
            path,
            array::len(path) - 1 as degrees_of_separation,
            first(path) as origin_user,
            last(path) as target_user,
            array::slice(path, 1, -1) as intermediary_users
        FROM (
            SELECT * FROM $origin ->(friends WHERE degree <= $max_degree)->users
            WHERE id = $target
        )
        ORDER BY degrees_of_separation ASC
        LIMIT 1;
        """
        
        result = await self.db.query(
            query,
            {
                "origin": origin_id,
                "target": target_id,
                "max_degree": max_degree
            }
        )
        
        if not result[0]["result"]:
            return {
                "connected": False,
                "message": f"No path found within {max_degree} degrees of separation"
            }
            
        return {
            "connected": True,
            **result[0]["result"][0]
        }

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
                CREATE friends SET 
                    in = $origin,
                    out = $target,
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
                "status": data.get("status", "accepted")
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
        result = await self.db.query(
            "DELETE users WHERE id = type::thing('users', $id);",
            {"id": id}
        )
        return result[0]["result"][0] if result[0]["result"] else None

    async def update(self, data: dict) -> dict:
        """
        Update user data
        
        Args:
            data (dict): User data to update, must include 'id' field
            
        Returns:
            dict: Updated user data
        """
        result = await self.db.query(
            "UPDATE $record_id MERGE $content",
            {"content": data, "record_id": data["id"]},
        )
        return result[0]["result"][0]


class UsersDB:
    def __init__(self, db: AsyncSurrealDB) -> None:
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
    db = AsyncSurrealDB(app.config["SURREAL_URI"])
    await db.connect()

    await db.sign_in(
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )
    await db.use("partyscene", "partyscene")
    return UsersDB(db)
