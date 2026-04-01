from quart import Quart
from surrealdb import AsyncSurreal, RecordID
import os

from shared.utils import record_id_to_json, report_resource
from purreal import SurrealDBConnectionPool, SurrealDBPoolManager


class LiveStreamDB:
    def __init__(self, pool: SurrealDBConnectionPool) -> None:
        self.pool: SurrealDBConnectionPool = pool

    async def _info(self):
        """Get database information."""
        return await self.pool.execute_query("INFO FOR DB")

    async def _report_resource(self, data: dict):
        """
        Report a livestream/scene resource.
        
        Args:
            data (dict): The data to report containing:
                - reporter: User ID who is reporting
                - resource: Scene ID being reported
                - reason: Reason for the report
        
        Returns:
            dict: Created report record
        """
        return await report_resource(self.pool, data, resource_table="scenes")

    async def fetch_cloudflare_scene(self, event_id: str, user_id: str = None):
        """
        Get Cloudflare scene data for an event.
        If user_id is provided, returns only that user's stream.
        Otherwise, returns all streams for the event with user information.
        
        Args:
            event_id: Event identifier
            user_id: Optional user identifier to fetch specific stream
            
        Returns:
            dict or list: Single stream if user_id provided, otherwise list of all streams
        """
        async with self.pool.acquire() as conn:
            if user_id:
                # Fetch specific user's stream
                result = await conn.query(
                    """
                    SELECT *, user.{id, first_name, last_name, username, avatar} as user_info 
                    FROM ONLY scenes 
                    WHERE event = type::thing("events", $event_id) 
                    AND user = type::thing("users", $user_id)
                    """,
                    {"event_id": event_id, "user_id": user_id},
                )
                return record_id_to_json(result)
            else:
                # Fetch all streams for the event
                result = await conn.query(
                    """
                    SELECT *, user.{id, first_name, last_name, username, avatar} as user_info 
                    FROM scenes 
                    WHERE event = type::thing("events", $event_id)
                    ORDER BY created_at DESC
                    """,
                    {"event_id": event_id},
                )
                return record_id_to_json(result)

    async def update_cloudflare_scene_playback(self, scene_or_event_id: str, playback_data: dict, user_id: str = None):
        """
        Update the playback data (HLS/DASH URLs) for a scene.
        Called when video becomes available after stream starts.

        Args:
            scene_or_event_id (str): Scene or event identifier, provide event_id if user_id is provided
            playback_data (dict): Playback URLs from Cloudflare Video API
            user_id (str, optional): User ID if updating by event+user combination

        Returns:
            bool: True if update was successful
        """
        async with self.pool.acquire() as conn:
            if user_id:
                # Update specific user's stream for an event
                result = await conn.query(
                    """
                    UPDATE scenes SET playback = $playback 
                    WHERE event = type::thing("events", $event_id)
                    AND user = type::thing("users", $user_id)
                    """,
                    {
                        "event_id": scene_or_event_id,
                        "user_id": user_id,
                        "playback": playback_data or {},
                    },
                )
            else:
                # Update by direct scene ID
                result = await conn.query(
                    """
                    UPDATE $scene_id SET playback = $playback
                    """,
                    {
                        "scene_id": RecordID("scenes", scene_or_event_id) if ":" not in scene_or_event_id else scene_or_event_id,
                        "playback": playback_data or {},
                    },
                )
        return bool(result)

    async def delete_cloudflare_scene(self, event_id: str, user_id: str):
        """
        Delete the Cloudflare scene data for a specific user's stream on an event.

        Args:
            event_id (str): Unique identifier for the event
            user_id (str): Unique identifier for the user

        Returns:
            bool: True if deletion was successful, False if scene not found
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                DELETE scenes 
                WHERE event = type::thing("events", $event_id) 
                AND user = type::thing("users", $user_id)
                """,
                {"event_id": event_id, "user_id": user_id},
            )
        return bool(result)
    
    async def update_scene_live_start(self, scene_id: str):
        """
        Set the live_started_at timestamp for a scene when it goes live.
        
        Args:
            scene_id (str): Scene record ID
            
        Returns:
            bool: True if update was successful
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                UPDATE $scene_id SET live_started_at = time::now() 
                WHERE live_started_at = NONE
                """,
                {"scene_id": RecordID("scenes", scene_id) if ":" not in scene_id else scene_id},
            )
        return bool(result)
    
    async def fetch_expired_scenes(self, max_live_seconds: int = 180):
        """
        Fetch all scenes that have been live for longer than the specified duration.
        
        Args:
            max_live_seconds (int): Maximum seconds a stream can be live (default 180 = 3 minutes)
            
        Returns:
            list: List of expired scene records with input_uid, event, and user info
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                SELECT *, user.{id, first_name, last_name, username} as user_info 
                FROM scenes 
                WHERE live_started_at != NONE 
                AND live_started_at + 3m < time::now()
                """,
            )
            return record_id_to_json(result) if result else []
    
    async def delete_scene_by_id(self, scene_id: str):
        """
        Delete a scene by its record ID.
        
        Args:
            scene_id (str): Scene record ID
            
        Returns:
            bool: True if deletion was successful
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                "DELETE $scene_id",
                {"scene_id": RecordID("scenes", scene_id) if ":" not in scene_id else scene_id},
            )
        return bool(result)




async def init_db(app) -> tuple[LiveStreamDB, SurrealDBPoolManager]:
    """
    Initialize the database connection pool and return an LiveStreamDB instance.

    Args:
        app: The Quart application instance

    Returns:
        LiveStreamDB: Initialized database connector
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
        name="scenes_pool",
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
        connection_retry_delay=2.0,
        schema_file=SCHEMA_FILE,
        reset_on_return=True,
        log_queries=True,
    )

    # Create LiveStreamDB instance
    livestream_db = LiveStreamDB(pool)

    return livestream_db, pool_manager