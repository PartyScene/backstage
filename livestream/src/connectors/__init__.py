from cloudflare.types.stream.live_input import LiveInput
from quart import Quart
from surrealdb import AsyncSurreal, RecordID
import os

from shared.utils import record_id_to_json
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
                - resource: Scene/event ID being reported
                - reason: Reason for the report
        
        Returns:
            dict: Created report record
        """
        data["reporter"] = RecordID("users", data["reporter"])
        data["resource"] = RecordID("scenes", data["resource"])
        async with self.pool.acquire() as conn:
            result = await conn.create("reports", data)
            return record_id_to_json(result)

    async def store_cloudflare_scene(self, input_response: dict | LiveInput, event_id: str, user_id: str):
        """
        Store the ingest url / playback url / from Cloudflare and attach it to the event and user.
        Supports SRT, RTMPS, WebRTC ingest and HLS/DASH playback.

        Args:
            input_response: Cloudflare LiveInput object or dict with stream configuration
            event_id: Unique identifier for the event
            user_id: Unique identifier for the user creating the stream

        Returns:
            dict: Created scene record with all stream data
        """
        # Handle both dict (from direct API) and LiveInput object (from SDK)
        if isinstance(input_response, dict):
            data = {
                "input_uid": input_response.get("uid", ""),
                "srt": input_response.get("srt", {}),
                "srtPlayback": input_response.get("srtPlayback", {}),
                "rtmps": input_response.get("rtmps", {}),
                "rtmpsPlayback": input_response.get("rtmpsPlayback", {}),
                "webRTC": input_response.get("webRTC", {}),
                "webRTCPlayback": input_response.get("webRTCPlayback", {}),
                "playback": {},
                "metadata": {
                    "created": input_response.get("created"),
                    "modified": input_response.get("modified"),
                    "status": input_response.get("status"),
                    "deleteRecordingAfterDays": input_response.get("deleteRecordingAfterDays"),
                    "meta": input_response.get("meta", {}),
                },
                "event_id": event_id,
                "user_id": user_id,
            }
        else:
            # Handle LiveInput object
            data = {
                "input_uid": input_response.uid or "",
                "srt": input_response.srt.model_dump() if input_response.srt else {},
                "srtPlayback": input_response.srt_playback.model_dump() if input_response.srt_playback else {},
                "rtmps": input_response.rtmps.model_dump() if input_response.rtmps else {},
                "rtmpsPlayback": input_response.rtmps_playback.model_dump() if input_response.rtmps_playback else {},
                "webRTC": input_response.web_rtc.model_dump() if input_response.web_rtc else {},
                "webRTCPlayback": input_response.web_rtc_playback.model_dump() if input_response.web_rtc_playback else {},
                "playback": {},
                "metadata": {
                    "created": str(input_response.created) if input_response.created else None,
                    "modified": str(input_response.modified) if input_response.modified else None,
                    "status": input_response.status if input_response.status else None,
                    "deleteRecordingAfterDays": input_response.delete_recording_after_days if input_response.delete_recording_after_days else None,
                    "meta": input_response.meta if input_response.meta else {},
                },
                "event_id": event_id,
                "user_id": user_id,
            }
        
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                INSERT INTO scenes 
                    (input_uid, srt, srtPlayback, rtmps, rtmpsPlayback, webRTC, webRTCPlayback, playback, metadata, event, user) 
                VALUES ($input_uid, $srt, $srtPlayback, $rtmps, $rtmpsPlayback, $webRTC, $webRTCPlayback, $playback, $metadata, type::thing("events", $event_id), type::thing("users", $user_id))
                """,
                data,
            )
        return record_id_to_json(result)

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

    async def update_cloudflare_scene_playback(self, scene_id: str, playback_data: dict, user_id: str = None):
        """
        Update the playback data (HLS/DASH URLs) for a scene.
        Called when video becomes available after stream starts.

        Args:
            scene_id (str): Scene record ID (e.g., "scenes:abc123") OR event_id if user_id provided
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
                        "event_id": scene_id,  # scene_id is actually event_id in this case
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
                        "scene_id": RecordID("scenes", scene_id) if ":" not in scene_id else scene_id,
                        "playback": playback_data or {},
                    },
                )
        return bool(result and result[0])

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
        return bool(result and result[0])

    # async def delete(self, email) :
    #     """This db function deletes a user.

    #     Args:
    #         email (__string_): The user email to delete.
    #     """
    #     result = await self.db.query(
    #         "DELETE users WHERE email = $email;", {"email": email}
    #     )
    #     return result[0]["result"][0]

    # async def update(self, data: dict):
    #     """This function updates a specific field

    #     Args:
    #         data (dict): _description_
    #     """
    #     record_id = (
    #         await self.db.query(
    #             "SELECT id FROM users WHERE email = $email;",
    #             {"email": data["email"]},
    #         )
    #     )[0]["result"][0]["id"]
    #     result = await self.db.query(
    #         "UPDATE $record_id MERGE $content",
    #         {"content": data, "record_id": record_id},
    #     )
    #     return result


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
        max_idle_time=300,
        connection_timeout=10.0,  # Increased from 5s to allow slower connection establishment
        acquisition_timeout=30.0,  # Increased from 10s to 30s to prevent premature cancellation
        health_check_interval=30,
        max_usage_count=1000,
        connection_retry_attempts=3,
        connection_retry_delay=2.0,
        schema_file=SCHEMA_FILE,
        reset_on_return=True,
        log_queries=True,
    )

    # Create LiveStreamDB instance
    livestream_db = LiveStreamDB(pool)

    return livestream_db, pool_manager