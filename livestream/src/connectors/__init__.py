from cloudflare.types.stream.live_input import LiveInput
from quart import Quart
from surrealdb import AsyncSurreal
import os

from shared.utils import record_id_to_json
from purreal import SurrealDBConnectionPool, SurrealDBPoolManager


class LiveStreamDB:
    def __init__(self, pool: SurrealDBConnectionPool) -> None:
        self.pool: SurrealDBConnectionPool = pool

    async def _info(self):
        """Get database information."""
        return await self.pool.execute_query("INFO FOR DB")

    async def store_cloudflare_scene(self, input_response: LiveInput, event_id: str):
        """
        Store the ingest url / playback url / from Cloudflare and attach it to the event.
        Supports SRT, RTMPS, WebRTC ingest and HLS/DASH playback.

        Args:
            input_response: Cloudflare LiveInput object with stream configuration
            event_id: Unique identifier for the event

        Returns:
            dict: Created scene record with all stream data
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                INSERT INTO scenes 
                    (input_uid, srt, srtPlayback, rtmps, rtmpsPlayback, webRTC, webRTCPlayback, playback, metadata, event) 
                VALUES ($input_uid, $srt, $srtPlayback, $rtmps, $rtmpsPlayback, $webRTC, $webRTCPlayback, $playback, $metadata, type::thing("events", $event_id))
                """,
                {
                    "input_uid": input_response.uid or "",
                    "srt": input_response.srt.model_dump() if input_response.srt else {},
                    "srtPlayback": input_response.srt_playback.model_dump() if input_response.srt_playback else {},
                    "rtmps": input_response.rtmps.model_dump() if input_response.rtmps else {},
                    "rtmpsPlayback": input_response.rtmps_playback.model_dump() if input_response.rtmps_playback else {},
                    "webRTC": input_response.web_rtc.model_dump() if input_response.web_rtc else {},
                    "webRTCPlayback": input_response.web_rtc_playback.model_dump() if input_response.web_rtc_playback else {},
                    "playback": {},  # HLS/DASH URLs populated from video API after stream starts
                    "metadata": {
                        "created": str(input_response.created) if input_response.created else None,
                        "modified": str(input_response.modified) if input_response.modified else None,
                        "status": input_response.status if input_response.status else None,
                        "deleteRecordingAfterDays": input_response.delete_recording_after_days if input_response.delete_recording_after_days else None,
                        "meta": input_response.meta if input_response.meta else {},
                    },
                    "event_id": event_id,
                },
            )
        return record_id_to_json(result)

    async def fetch_cloudflare_scene(self, event_id: str):
        """
        Get the current Cloudflare scene data attached to an event
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                SELECT * FROM ONLY scenes WHERE event = type::thing("events", $event_id)
                """,
                {"event_id": event_id},
            )
        return record_id_to_json(result)

    async def update_cloudflare_scene_playback(self, event_id: str, playback_data: dict):
        """
        Update the playback data (HLS/DASH URLs) for a scene.
        Called when video becomes available after stream starts.

        Args:
            event_id (str): Unique identifier for the event
            playback_data (dict): Playback URLs from Cloudflare Video API

        Returns:
            bool: True if update was successful
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                UPDATE scenes SET playback = $playback 
                WHERE event = type::thing("events", $event_id)
                """,
                {
                    "event_id": event_id,
                    "playback": playback_data or {},
                },
            )
        return bool(result and result[0])

    async def delete_cloudflare_scene(self, event_id: str):
        """
        Delete the Cloudflare scene data for an event

        Args:
            event_id (str): Unique identifier for the event

        Returns:
            bool: True if deletion was successful, False if scene not found
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                DELETE scenes WHERE event = type::thing("events", $event_id)
                """,
                {"event_id": event_id},
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
        min_connections=2,
        max_connections=10,
        max_idle_time=300,
        connection_timeout=5.0,
        acquisition_timeout=10.0,
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

    # For backward compatibility with existing code
    # This allows code that directly accesses LiveStreamDB.db to still work
    async with pool.acquire() as conn:
        livestream_db.pool = conn

    return livestream_db, pool_manager
