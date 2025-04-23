import os
import asyncio
import logging

from cloudflare import AsyncCloudflare
from cloudflare.types import stream
from livestream.src.connectors import LiveStreamDB


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
        self.conn : LiveStreamDB = app.conn
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

    async def retrieve_account(self):
        """
        Retrieve the Cloudflare account ID for the 'Partyscene' account.

        Sets the `ACCOUNT_ID` attribute with the found account's identifier.
        """
        accounts = await self.client.accounts.list()
        self.ACCOUNT_ID = accounts.result[0].id
        if not accounts.result:
            self.logger.warning("CLOUDFLARE ACCOUNT ID NOT FOUND")
            return
        # Find the account with the name 'Partyscene'
        # for account in accounts.result:
        #     if account.name == "Partyscene":
        #         self.ACCOUNT_ID = account.id
                # break

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

    async def _create_input(self, event_id):
        """
        Create a new Cloudflare live input for streaming.

        Args:
            event_id (str): Unique identifier for the event

        Returns:
            stream.LiveInput: Created live input configuration
        """
        if not self.ACCOUNT_ID:
            self.logger.warning("CLOUDFLARE ACCOUNT ID NOT FOUND, FETCHING...")
            await self.retrieve_account()
            
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
        return input

    async def _delete_input(self, input_id):
        """
        Delete a Cloudflare live input.

        Args:
            input_id (str): Unique identifier of the live input to delete
        """
        await self.client.stream.live_inputs.delete(
            live_input_identifier=input_id,
            account_id=self.ACCOUNT_ID,
        )

    async def fetch_stream(self, event_id):
        """
        Fetch stream information for a specific event from the application's connection.

        Args:
            event_id (str): Unique identifier for the event

        Returns:
            Dict: Stream information or None if not found
        """
        return await self.conn.fetch_cloudflare_scene(event_id)

    async def create_stream(self, event_id):
        """
        Initiate a new livestream for a specific event.

        Creates a Cloudflare stream input, stores the scene information,
        and prepares the stream for broadcasting.

        Args:
            event_id (str): Unique identifier for the event

        Returns:
            bool: True if the stream was successfully created
        """
        self.logger.warning("CREATING INPUT FOR LIVESTREAM FOR EVENT %s" % event_id)
        input_response = await self._create_input(event_id)

        # self.logger.info("CREATING CHANNEL FOR LIVESTREAM FOR EVENT %s" % event)
        # channel_response = await self._create_channel(input_response.name)

        await self.conn.store_cloudflare_scene(input_response, event_id)
        # await self._start_channel(channel_response.name)
        self.logger.warning("CREATED LIVESTREAM FOR EVENT %s" % event_id)
        return True

    async def delete_stream(self, event_id):
        """
        Delete the livestream input for a specific event.

        Removes the Cloudflare stream input associated with the event.

        Args:
            event_id (str): Unique identifier for the event

        Returns:
            bool: True if the stream was successfully deleted
        """
        self.logger.warning("DELETING INPUT FOR LIVESTREAM FOR EVENT %s" % event_id)
        scene_info = await self.fetch_stream(event_id)
        if scene_info:
            await self._delete_input(scene_info["input_uid"])
            # await self.app.conn.delete_cloudflare_input(event_id)
        self.logger.warning(
            "DONE DELETING INPUT FOR LIVESTREAM FOR EVENT %s" % event_id
        )
        return True

    async def get_vods(self, event_id):
        """
        Retrieve video-on-demand (VOD) recordings for a specific event.

        Args:
            event_id (str): Unique identifier for the event

        Returns:
            List[stream.Video]: List of VOD videos for the event
        """
        self.logger.warning("GETTING VODS FOR EVENT %s" % event_id)
        scene_info = await self.fetch_stream(event_id)
        if scene_info:
            return await self._retrieve_video(event_id)
        return []

    async def get_live(self, event_id):
        """
        Retrieve the current live stream for a specific event.

        Args:
            event_id (str): Unique identifier for the event

        Returns:
            List[stream.Video]: List of live streams for the event
        """
        self.logger.warning("GETTING LIVE FOR EVENT %s" % event_id)
        scene_info = await self.fetch_stream(event_id)
        if scene_info:
            return await self._retrieve_video(event_id, live=True)
        return []
