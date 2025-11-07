import os
import asyncio
import logging

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
            api_email=os.environ.get(
                "CLOUDFLARE_ACCOUNT_EMAIL"
            ),  # This is the default and can be omitted
            api_key=os.environ.get(
                "CLOUDFLARE_API_KEY"
            ),  # This is the default and can be omitted
        )
        self.ACCOUNT_ID = ""
        self._initialized = False

    async def initialize(self):
        """
        Initialize async resources. Must be called after __init__.
        Fetches and validates Cloudflare account ID.
        """
        if self._initialized:
            return

        try:
            await self.retrieve_account()
            if not self.ACCOUNT_ID:
                raise RuntimeError(
                    "Failed to retrieve Cloudflare account ID. Check API credentials."
                )
            self.logger.info(
                f"CloudflareLSClient initialized with account ID: {self.ACCOUNT_ID}"
            )
            self._initialized = True
        except Exception as e:
            self.logger.error(f"Failed to initialize CloudflareLSClient: {e}")
            raise

    async def retrieve_account(self):
        """
        Retrieve the Cloudflare account ID.

        Sets the `ACCOUNT_ID` attribute with the found account's identifier.

        Raises:
            RuntimeError: If no accounts are found or API call fails
        """
        try:
            accounts = await self.client.accounts.list()
            if not accounts.result:
                self.logger.error("No Cloudflare accounts found")
                raise RuntimeError("No Cloudflare accounts available")

            self.ACCOUNT_ID = accounts.result[0].id
            self.logger.info(f"Retrieved Cloudflare account ID: {self.ACCOUNT_ID}")
        except APIError as e:
            self.logger.error(f"Cloudflare API error retrieving account: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error retrieving account: {e}")
            raise

    async def _retrieve_video(
        self, event_id, live: bool = False, retrieve_all: bool = False
    ):
        """
        Retrieve video(s) associated with a specific event.

        Args:
            event_id (str): Unique identifier for the event
            live (bool, optional): Whether to retrieve live streams. Defaults to False.
            retrieve_all (bool, optional): If True, returns all matching videos. Defaults to False.

        Returns:
            Union[stream.Video, List[stream.Video], None]: Retrieved video(s) or None
        """
        videos = await self.client.stream.list(
            account_id=self.ACCOUNT_ID,
            search=event_id,
            asc=False,
            status="ready",
            type="live" if live else "vod",
        )
        return (
            videos.result
            if retrieve_all
            else (videos.result[0].to_json() if videos.result else None)
        )

    @retry(
        retry=retry_if_exception_type((APIConnectionError, APITimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
    )
    async def _create_input(self, event_id: str) -> LiveInput:
        """
        Create a new Cloudflare live input for streaming with retry logic.

        Args:
            event_id (str): Unique identifier for the event

        Returns:
            stream.LiveInput: Created live input configuration

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
            input = await self.client.stream.live_inputs.create(
                account_id=self.ACCOUNT_ID,
                delete_recording_after_days=90.0,
                meta={"name": event_id},
                recording={
                    "mode": "automatic",
                    "require_signed_urls": False,
                    "allowed_origins": ["*"],
                },
            )
            self.logger.info(
                f"Successfully created live input {input.uid} for event {event_id}"
            )
            return input
        except APIError as e:
            self.logger.error(
                f"Cloudflare API error creating input for event {event_id}: {e.message if hasattr(e, 'message') else str(e)}"
            )
            raise
        except Exception as e:
            self.logger.error(
                f"Unexpected error creating input for event {event_id}: {e}"
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

    async def fetch_stream(self, event_id):
        """
        Fetch stream information for a specific event from the application's connection.

        Args:
            event_id (str): Unique identifier for the event

        Returns:
            Dict: Stream information or None if not found
        """
        return await self.conn.fetch_cloudflare_scene(event_id)

    async def create_stream(self, event_id: str) -> bool:
        """
        Initiate a new livestream for a specific event.

        Creates a Cloudflare stream input, stores the scene information,
        and prepares the stream for broadcasting.

        Args:
            event_id (str): Unique identifier for the event

        Returns:
            bool: True if the stream was successfully created

        Raises:
            ValueError: If stream already exists for this event
            APIError: If Cloudflare API fails
            Exception: For database or other errors
        """
        # Check for existing stream (idempotency)
        existing_stream = await self.fetch_stream(event_id)
        if existing_stream:
            self.logger.warning(
                f"Stream already exists for event {event_id}, returning existing stream"
            )
            return True

        self.logger.info(f"Creating livestream for event {event_id}")
        try:
            input_response = await self._create_input(event_id)
            await self.conn.store_cloudflare_scene(input_response, event_id)
            self.logger.info(f"Successfully created livestream for event {event_id}")
            return True
        except Exception as e:
            self.logger.error(
                f"Failed to create livestream for event {event_id}: {e}", exc_info=True
            )
            raise

    async def delete_stream(self, event_id: str) -> bool:
        """
        Delete the livestream input for a specific event.

        Removes both the Cloudflare stream input and database record.

        Args:
            event_id (str): Unique identifier for the event

        Returns:
            bool: True if the stream was successfully deleted, False if stream not found

        Raises:
            APIError: If Cloudflare API fails
            Exception: For other errors
        """
        self.logger.info(f"Deleting livestream for event {event_id}")
        scene_info = await self.fetch_stream(event_id)
        if not scene_info:
            self.logger.warning(f"No stream found for event {event_id}")
            return False

        try:
            # Delete from Cloudflare first
            await self._delete_input(scene_info["input_uid"])
            # Then delete from database
            await self.conn.delete_cloudflare_scene(event_id)
            self.logger.info(f"Successfully deleted livestream for event {event_id}")
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

            video_data = await self._retrieve_video(event_id)
            if video_data:
                self.logger.info(f"Found VOD for event {event_id}")
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

            video_data = await self._retrieve_video(event_id, live=True)
            if video_data:
                self.logger.info(f"Found live stream for event {event_id}")
            else:
                self.logger.info(
                    f"Live stream not ready yet for event {event_id} (may still be processing)"
                )
            return video_data
        except Exception as e:
            self.logger.error(f"Error retrieving live stream for event {event_id}: {e}")
            raise
