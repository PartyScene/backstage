import os
import asyncio
import logging
import orjson as json

from cloudflare import AsyncCloudflare
from cloudflare.types import stream
from cloudflare.types.stream import LiveInput
from cloudflare._exceptions import APIError, APIConnectionError, APITimeoutError
from livestream.src.connectors import LiveStreamDB
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
import rusty_req
from shared.utils import parse_rusty_req_response


class CloudflareLSClient:
    def __init__(self, app, *args, **kwargs):
        """
        Initialize a Cloudflare Stream client for managing live streaming and video on demand.

        Args:
            app: The application context providing logging and connection utilities
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments
        """
        self.app = app
        self.conn: LiveStreamDB = app.conn
        self.logger = app.logger
        self.client = AsyncCloudflare(
            api_token=os.environ.get("CLOUDFLARE_API_TOKEN"),
        )
        self.ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        self.API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
        self._initialized = False

    async def initialize(self):
        """
        Initialize async resources. Must be called after __init__.
        Validates Cloudflare account ID is configured.
        """
        if self._initialized:
            return

        try:
            if not self.ACCOUNT_ID:
                raise RuntimeError(
                    "CLOUDFLARE_ACCOUNT_ID environment variable not set. Get it from Cloudflare dashboard."
                )
            self.logger.info(
                f"CloudflareLSClient initialized with account ID: {self.ACCOUNT_ID}"
            )
            self._initialized = True
        except Exception as e:
            self.logger.error(f"Failed to initialize CloudflareLSClient: {e}")
            raise

    async def _call_cloudflare_api(self, url: str, method: str = "GET", params: dict = None) -> dict:
        """
        Helper method to call Cloudflare API using rusty_req.
        
        Args:
            url (str): Full API URL
            method (str): HTTP method (GET, POST, etc.)
            params (dict): Request body for POST/PUT requests
            
        Returns:
            dict: Parsed response result from Cloudflare API
            
        Raises:
            APIError: If API call fails
        """
        headers = {
            "Authorization": f"Bearer {self.API_TOKEN}",
            "Content-Type": "application/json",
        }
        
        response = await rusty_req.fetch_single(
            url=url,
            method=method,
            headers=headers,
            params=params,
            timeout=10.0,
            tag=f"cloudflare-{method.lower()}",
        )
        
        try:
            # Use shared helper for parsing rusty_req response
            result = parse_rusty_req_response(response, expected_status=(200, 201))
            
            # Cloudflare API wraps response in success/result structure
            if not result.get("success"):
                raise APIError(
                    f"Cloudflare API call unsuccessful: {result}",
                    response=None,
                    body=result,
                )
            
            return result.get("result")
        except RuntimeError as e:
            # Convert RuntimeError from helper to APIError for consistency
            raise APIError(str(e), response=None, body=None)

    async def _retrieve_video(self, input_uid: str, live_only: bool = False):
        """
        Retrieve video playback info from a live input.
        
        Per Cloudflare docs: https://developers.cloudflare.com/stream/stream-live/watch-live-stream/
        - First video in list has status "live-inprogress" if actively broadcasting
        - Other videos have status "ready" (recordings)
        - Returns playback.hls and playback.dash URLs

        Args:
            input_uid (str): Cloudflare live input UID
            live_only (bool): If True, only return live-inprogress videos. Default False.

        Returns:
            dict or None: Video with playback info (HLS/DASH URLs)
        """
        # Get list of videos using direct API call (not in Python SDK)
        # https://api.cloudflare.com/client/v4/accounts/{account_id}/stream/live_inputs/{input_uid}/videos
        url = f"https://api.cloudflare.com/client/v4/accounts/{self.ACCOUNT_ID}/stream/live_inputs/{input_uid}/videos"
        
        try:
            videos = await self._call_cloudflare_api(url)
        except APIError as e:
            self.logger.error(f"Failed to get videos for input {input_uid}: {e}")
            return None
        
        if not videos:
            return None
        
        # First video is live-inprogress if actively broadcasting, otherwise most recent recording
        # Per Cloudflare docs, the video already includes playback.hls and playback.dash URLs
        first_video = videos[0]
        
        # If live_only flag is set, only return live-inprogress videos
        if live_only:
            video_status = first_video.get("status", {})
            if isinstance(video_status, dict) and video_status.get("state") == "live-inprogress":
                return first_video
            return None
        
        # Otherwise return any video with playback available
        if first_video.get("playback"):
            return first_video
        
        return None

    @retry(
        retry=retry_if_exception_type((APIConnectionError, APITimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
    )
    async def _create_input(self, event_id: str) -> dict:
        """
        Create a new Cloudflare live input for streaming with retry logic.
        Uses direct API calls to avoid SDK body encoding issues.

        Args:
            event_id (str): Unique identifier for the event

        Returns:
            dict: Created live input configuration from Cloudflare API

        Raises:
            RuntimeError: If client not initialized
            APIError: If Cloudflare API returns an error
        """
        if not self._initialized:
            raise RuntimeError(
                "CloudflareLSClient not initialized. Call initialize() first."
            )

        try:
            self.logger.info(f"Creating Cloudflare live input for event {event_id}")
            
            url = f"https://api.cloudflare.com/client/v4/accounts/{self.ACCOUNT_ID}/stream/live_inputs"
            params = {
                "deleteRecordingAfterDays": 90,
                "meta": {"name": event_id},
                "recording": {"mode": "automatic"},
            }
            
            live_input = await self._call_cloudflare_api(url, method="POST", params=params)
            self.logger.info(
                f"Successfully created live input {live_input.get('uid')} for event {event_id}"
            )
            return live_input
            
        except APIError:
            raise
        except Exception as e:
            self.logger.error(
                f"Unexpected error creating input for event {event_id}: {e}",
                exc_info=True,
            )
            raise

    async def _delete_input(self, input_id: str) -> bool:
        """
        Delete a Cloudflare live input.

        Args:
            input_id (str): Unique identifier of the live input to delete

        Returns:
            bool: True if deletion was successful

        Raises:
            APIError: If Cloudflare API returns an error
        """
        try:
            self.logger.info(f"Deleting Cloudflare live input {input_id}")
            await self.client.stream.live_inputs.delete(
                live_input_identifier=input_id,
                account_id=self.ACCOUNT_ID,
            )
            self.logger.info(f"Successfully deleted live input {input_id}")
            return True
        except APIError as e:
            self.logger.error(
                f"Cloudflare API error deleting input {input_id}: {e.message if hasattr(e, 'message') else str(e)}"
            )
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error deleting input {input_id}: {e}")
            raise

    async def fetch_stream(self, event_id, user_id=None):
        """
        Fetch stream information for a specific event from the application's connection.

        Args:
            event_id (str): Unique identifier for the event
            user_id (str, optional): Unique identifier for the user

        Returns:
            Dict or List: Stream information or None if not found
        """
        return await self.conn.fetch_cloudflare_scene(event_id, user_id)

    async def create_stream(self, event_id: str, user_id: str):
        """
        Initiate a new livestream for a specific user at an event.

        Creates a Cloudflare stream input, stores the scene information,
        and prepares the stream for broadcasting.

        Args:
            event_id (str): Unique identifier for the event
            user_id (str): Unique identifier for the user creating the stream

        Returns:
            LiveInput: Cloudflare LiveInput object with stream credentials

        Raises:
            ValueError: If stream already exists for this user/event
            APIError: If Cloudflare API fails
            Exception: For database or other errors
        """
        # Check for existing stream (idempotency)
        existing_stream = await self.fetch_stream(event_id, user_id)
        if existing_stream:
            self.logger.warning(
                f"Stream already exists for user {user_id} on event {event_id}"
            )
            return existing_stream

        self.logger.info(f"Creating livestream for user {user_id} on event {event_id}")
        try:
            # Use user_id in the stream name for uniqueness
            input_response = await self._create_input(f"{event_id}_{user_id}")
            self.logger.info(f"Successfully created livestream for user {user_id} on event {event_id}")
            return input_response
        except Exception as e:
            self.logger.error(
                f"Failed to create livestream for user {user_id} on event {event_id}: {e}", exc_info=True
            )
            raise

    async def delete_stream(self, event_id: str, user_id: str) -> bool:
        """
        Delete the livestream input for a specific user's stream on an event.

        Removes both the Cloudflare stream input and database record.

        Args:
            event_id (str): Unique identifier for the event
            user_id (str): Unique identifier for the user

        Returns:
            bool: True if the stream was successfully deleted, False if stream not found

        Raises:
            APIError: If Cloudflare API fails
            Exception: For other errors
        """
        self.logger.info(f"Deleting livestream for user {user_id} on event {event_id}")
        scene_info = await self.fetch_stream(event_id, user_id)
        if not scene_info:
            self.logger.warning(f"No stream found for user {user_id} on event {event_id}")
            return False

        try:
            # Delete from Cloudflare first
            await self._delete_input(scene_info["input_uid"])
            self.logger.info(f"Successfully deleted livestream for user {user_id} on event {event_id}")
            return True
        except Exception as e:
            self.logger.error(
                f"Failed to delete livestream for event {event_id}: {e}",
                exc_info=True,
            )
            raise

    async def get_vods(self, event_id: str):
        """
        Retrieve video-on-demand (VOD) recordings for a specific event.

        Args:
            event_id (str): Unique identifier for the event

        Returns:
            Video data or None: VOD video for the event or None if not found
        """
        self.logger.info(f"Retrieving VODs for event {event_id}")
        try:
            scene_info = await self.fetch_stream(event_id)
            if not scene_info:
                self.logger.info(f"No scene info found for event {event_id}")
                return None

            input_uid = scene_info.get("input_uid")
            if not input_uid:
                self.logger.error(f"No input_uid found in scene_info for event {event_id}")
                return None

            video_data = await self._retrieve_video(input_uid)
            if video_data:
                self.logger.info(f"Found VOD for event {event_id}")
                # Update database with playback URLs
                if isinstance(video_data, dict) and "playback" in video_data:
                    await self.conn.update_cloudflare_scene_playback(event_id, video_data["playback"])
                    self.logger.info(f"Updated playback data for event {event_id}")
            else:
                self.logger.info(f"No VOD available yet for event {event_id}")
            return video_data
        except Exception as e:
            self.logger.error(f"Error retrieving VODs for event {event_id}: {e}")
            raise

    async def get_live(self, event_id: str):
        """
        Retrieve the current live stream for a specific event.

        Args:
            event_id (str): Unique identifier for the event

        Returns:
            Video data or None: Live stream for the event or None if not found
        """
        self.logger.info(f"Retrieving live stream for event {event_id}")
        try:
            scene_info = await self.fetch_stream(event_id)
            if not scene_info:
                self.logger.info(f"No scene info found for event {event_id}")
                return None

            input_uid = scene_info.get("input_uid")
            if not input_uid:
                self.logger.error(f"No input_uid found in scene_info for event {event_id}")
                return None

            video_data = await self._retrieve_video(input_uid, live_only=True)
            if video_data:
                self.logger.info(f"Found live stream for event {event_id}")
                # Update database with playback URLs
                if isinstance(video_data, dict) and "playback" in video_data:
                    await self.conn.update_cloudflare_scene_playback(event_id, video_data["playback"])
                    self.logger.info(f"Updated playback data for event {event_id}")
            else:
                self.logger.info(
                    f"Live stream not ready yet for event {event_id} (may still be processing)"
                )
            return video_data
        except Exception as e:
            self.logger.error(f"Error retrieving live stream for event {event_id}: {e}")
            raise
