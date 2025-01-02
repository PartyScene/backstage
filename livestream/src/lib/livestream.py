# TODO:Create Live Stream module that will handle
# Input endpoint creation & Pooling
# Channel creation and assignment
# Failsafe for connectivity issues

from logging import Logger
import os
import uuid
from google.cloud.video import live_stream_v1 as ls1 
from google.cloud.video.live_stream_v1 import LivestreamServiceAsyncClient
from google.cloud.video.live_stream_v1.types import Manifest, AudioStream, VideoStream, MuxStream, ElementaryStream, Input, InputAttachment, Channel, ChannelOperationResponse

from src.connectors import LiveStreamDB


class LiveStream:
    
    def __init__(self, db, logger: Logger):
        self.PROJECT_ID = os.environ['GOOGLE_CLOUD_PROJECT']
        self.LOCATION = os.environ['LOCATION']
        self.STREAM_TYPE = os.environ['STREAM_TYPE']
        self.OUTPUT_URI = os.environ['OUTPUT_URI']
        self.client = LivestreamServiceAsyncClient()
        self.db : LiveStreamDB = db
        self.logger = logger
        
    def get_parent(self):
        return self._get_parent()
    
    async def start_stream(self, event) -> bool:
        """Creates a Stream link for this event, the Organizer client will send stream input to the input URI 

        Args:
            event (_type_): _description_
        Returns:
            bool: `True` if the stream was created successfully ig
        """ 
        self.logger.info("CREATING INPUT FOR LIVESTREAM FOR EVENT %s" % event)
        input_response = await self._create_input()
        
        self.logger.info("CREATING CHANNEL FOR LIVESTREAM FOR EVENT %s" % event)
        channel_response = await self._create_channel(input_response.name)
        
        await self.db.store_livestream(channel_response, input_response, event)
        await self._start_channel(channel_response.name)
        self.logger.info("DONE LIVESTREAM FOR EVENT %s" % event)
        return True
        
    async def get_stream(self, event : str):
        """Get the currently active Stream for an event

        Args:
            event (str): the event ID to fetch stream
        """
        self.logger.info("FETCHING STREAM DETAILS (CHANNEL, PLAYBACK_URL, INGEST_URL) FOR LIVESTREAM FOR EVENT %s" % event)
        result = await self.db.fetch_livestream(event)
        return result
    
    def _get_parent(self):
        return f"projects/{self.PROJECT_ID}/locations/{self.LOCATION}"
    
    async def _get_input(self, name):
        request = ls1.GetInputRequest(
            name=name,
        )

        # Make the request
        response = await self.client.get_input(request=request)

        # Handle the response
        return response
    
    async def _start_channel(self, name):
        request = ls1.StartChannelRequest(
            name=name,
        )

        # Make the request
        operation = await self.client.start_channel(request=request)

        print("Waiting for operation to complete...")

        response = await operation.result()

        # Handle the response
        print(response)
        
    async def _create_input(self) -> Input:
        """
        Create a livestream input using GCP Livestream API.
        """
        
        # Parent resource path in class definition
        
        input_id = str(uuid.uuid4())

        # Define the input configuration
        input_config = Input(type_="RTMP_PUSH")

        # Create input via LivestreamServiceClient
        operation = await self.client.create_input(parent=self.get_parent(), input=input_config, input_id=input_id)
        response = await operation.result()  # Wait for the operation to complete (900 seconds)
        return response
    
    async def _create_channel(self, input_name: str) -> Channel:
        """Generate a channel for this livestream using GCP Livestream API.

        Args:
            input_id (str): the input identifier
        """
        channel_id = str(uuid.uuid4())
        
         # Initialize request argument(s)
        channel = Channel(
            name=channel_id,
            input_attachments = [
                InputAttachment(
                    key = "%s-input" % (channel_id),
                    input = input_name
                )
            ],
            elementary_streams = [
                ElementaryStream(
                    key = "%s_es_video" % channel_id,
                    video_stream = VideoStream(
                        h264 = VideoStream.H264CodecSettings(
                            frame_rate=60,
                            width_pixels = 1920,
                            height_pixels = 1080,
                            bitrate_bps = 6000000
                        )
                    )
                ),
                ElementaryStream(
                    key="%s_es_audio" % channel_id,
                    audio_stream = AudioStream(
                        bitrate_bps = 1000000
                    )
                )
            ],
            mux_streams = [
                MuxStream(
                    key = "%s_mux_video" % (channel_id),
                    elementary_streams = ["%s_es_video" % channel_id],
                ),
                MuxStream(
                    key = "%s_mux_audio" % channel_id,
                    elementary_streams = ["%s_es_audio" % channel_id]
                )
            ],
            manifests = [
                Manifest(
                    file_name = "%s_manifest.m3u8" % channel_id,
                    type = self.STREAM_TYPE,
                    mux_streams = ["%s_mux_video" % channel_id, "%s_mux_audio" % channel_id],
                    
                )
            ],
            output=Channel.Output(uri=self.OUTPUT_URI),
            streaming_state=Channel.StreamingState.AWAITING_INPUT
        )
        # Make the request
        operation = await self.client.create_channel(parent=self.get_parent(), channel=channel, channel_id=channel_id)

        print("Waiting for operation to complete...")

        response = await operation.result()

        # Handle the response
        return response