from quart import (
    make_response,
    render_template,
    current_app as app,
    request,
    jsonify,
    Quart,
)
from quart.datastructures import FileStorage
from quart_jwt_extended import get_jwt_identity, jwt_required

from shared.classful import route, QuartClassful
from http import HTTPStatus
import os
from datetime import datetime, timedelta
from aiocache import cached
from typing import Literal, Sequence

import io
from importlib import util
from PIL import Image
import requests
from contextlib import asynccontextmanager

from obstore import store
import obstore as obs
from faststream.rabbit import RabbitBroker, RabbitMessage, RabbitQueue
import ormsgpack


class RMQBroker(RabbitBroker):

    def __init__(self, app: Quart, *args, **kwargs):
        self.RABBITMQ_MEDIA_QUEUE = RabbitQueue(os.environ["RABBITMQ_MEDIA_QUEUE"])
        self.RABBITMQ_R18E_QUEUE = RabbitQueue(os.environ["RABBITMQ_R18E_QUEUE"])
        self.OBS_STORE = store.GCSStore(os.environ["GCS_BUCKET_NAME"])

        self.logger = app.logger

        if app.microservice_instance.needs_rmq():
            super().__init__(
                url=os.environ["RABBITMQ_URI"],
                decoder=self.decode_message,
                *args,
                **kwargs
            )

        if app.microservice_instance == "MEDIA":
            from obstore.auth.google import GoogleCredentialProvider

            # self.OBS_STORE = GCSStore(os.environ["GCS_BUCKET_NAME"])
            credential_provider = GoogleCredentialProvider()
            self.logger.warning(
                "USING OBS WITH GCS_BUCKET_URI: %s ", os.environ["GCS_BUCKET_URI"]
            )
            # self.OBS_STORE = store.from_url(
            #     os.environ["GCS_BUCKET_URI"], credential_provider=credential_provider
            # )

            # @self.subscriber(self.RABBITMQ_MEDIA_QUEUE)
            # async def handle_url_signing(message: RabbitMessage):
            #     """
            #     This listener will generate PUT signed URLs for media uploads
            #     to be sent back to the client.

            #     Args:
            #         message (RabbitMessage): The message received from the queue
            #     """
            #     filenames = await self._create_put_urls_from_rmq(message.body)

            @self.subscriber(self.RABBITMQ_MEDIA_QUEUE)
            async def handle_media_upload(message):
                await self.upload_to_bucket(message.headers, message.body)
                # name = message.headers.get("filename", "")

                # if "event" in name:
                #     await self._publish_r18e(name, message.body, "MEDIA")
                # elif "post" in name:
                #     await self._publish_r18e(name, message.body, "POST")
                # else:
                #     app.logger.warning("Unknown filename: %s", name)

                await message.ack()

    async def decode_message(self, msg: RabbitMessage, original_decoder):
        try:
            msg.body = ormsgpack.unpackb(msg.body)
            return msg
        except:
            try:
                return await original_decoder(msg)
            except:
                return None

    async def convert_mov_to_mp4(self, input_bytes: bytes) -> bytes:
        """Convert MOV to MP4 using FFmpeg async API with hardware acceleration for iOS compatibility"""
        import tempfile
        from ffmpeg.asyncio import FFmpeg
        from ffmpeg.errors import FFmpegError
        
        # Create temporary files
        with tempfile.NamedTemporaryFile(suffix='.mov', delete=False) as temp_input:
            temp_input.write(input_bytes)
            temp_input_path = temp_input.name
        
        temp_output_path = temp_input_path.replace('.mov', '.mp4')
        
        try:
            # Try hardware acceleration first (NVIDIA)
            try:
                ffmpeg_hw = (
                    FFmpeg()
                    .option("y")  # Overwrite output file
                    .option("hwaccel", "cuda")  # Hardware acceleration
                    .input(temp_input_path)
                    .output(
                        temp_output_path,
                        {
                            "codec:v": "h264_nvenc",     # NVIDIA hardware encoder
                            "preset": "fast",            # Balance speed vs compression
                            "crf": "23",                 # Good quality/size balance
                            "profile:v": "baseline",     # iOS compatibility
                            "level": "3.0",              # iOS compatibility
                            "codec:a": "aac",            # AAC audio for iOS
                            "ar": "44100",               # Standard audio sample rate
                            "movflags": "+faststart",    # Enable progressive download
                            "pix_fmt": "yuv420p"         # iOS compatible pixel format
                        }
                    )
                )
                
                await ffmpeg_hw.execute()
                self.logger.info("Successfully converted MOV to MP4 using hardware acceleration")
                
            except FFmpegError as e:
                self.logger.info(f"Hardware acceleration unavailable, using software: {e}")
                
                # Fall back to software encoding
                ffmpeg_sw = (
                    FFmpeg()
                    .option("y")  # Overwrite output file
                    .input(temp_input_path)
                    .output(
                        temp_output_path,
                        {
                            "codec:v": "libx264",        # H.264 codec for iOS compatibility
                            "preset": "fast",            # Balance speed vs compression
                            "crf": "23",                 # Good quality/size balance
                            "profile:v": "baseline",     # iOS compatibility
                            "level": "3.0",              # iOS compatibility
                            "codec:a": "aac",            # AAC audio for iOS
                            "ar": "44100",               # Standard audio sample rate
                            "movflags": "+faststart",    # Enable progressive download
                            "pix_fmt": "yuv420p"         # iOS compatible pixel format
                        }
                    )
                )
                
                await ffmpeg_sw.execute()
                self.logger.info("Successfully converted MOV to MP4 using software encoding")
            
            # Read converted file
            with open(temp_output_path, 'rb') as f:
                converted_bytes = f.read()
                
            self.logger.info(f"Successfully converted MOV to MP4. Original: {len(input_bytes)} bytes, Converted: {len(converted_bytes)} bytes")
            return converted_bytes
            
        finally:
            # Clean up temp files
            for path in [temp_input_path, temp_output_path]:
                if os.path.exists(path):
                    os.unlink(path)

    async def upload_to_bucket(self, data, file_bytes: bytes):
        import obstore as obs
        
        # Check if this is a MOV file that needs conversion
        filename = data["filename"]
        content_type = data["content-type"]
        
        if filename.lower().endswith('.mov') and content_type.startswith('video/'):
            try:
                # Convert MOV to MP4
                file_bytes = await self.convert_mov_to_mp4(file_bytes)
                # Update filename and content type
                data["filename"] = filename.replace('.mov', '.mp4').replace('.MOV', '.mp4')
                data["content-type"] = 'video/mp4'
                self.logger.info(f"Converted MOV to MP4: {filename} -> {data['filename']}")
            except Exception as e:
                self.logger.error(f"Failed to convert MOV to MP4 for {filename}: {e}")
                # Continue with original file if conversion fails
        
        await obs.put_async(
            self.OBS_STORE,
            data["filename"],
            file_bytes,
            attributes={"Content-Type": data["content-type"]},
        )

    async def sign_put_urls(self, filenames: Sequence[str]):
        signed_urls = await obs.sign_async(
            self.OBS_STORE,
            "PUT",
            filenames,
            timedelta(seconds=60 * 60 * 6),
        )
        return signed_urls

    async def _publish_r18e(
        self, filename, file, type: Literal["MEDIA", "POST", "EVENT"]
    ):

        file = (
            ormsgpack.packb(file.read())
            if not isinstance(file, bytes)
            else ormsgpack.packb(file)
        )
        await self.publisher(self.RABBITMQ_R18E_QUEUE).publish(
            file,
            headers={"type": type, "filename": filename},
        )

    async def _publish_media(self, data: dict, file: io.BytesIO):
        """
        This method publishes a message to the media queue.
        Make sure to pass the following data in the dictionary:
            - filename
            - event
            - creator
            - type

        Args:
            data (dict): Dictionary containing the data to be published
            file (bytes): File to be published
        """
        file_bytes: bytes = ormsgpack.packb(file.read())
        await self.publisher(self.RABBITMQ_MEDIA_QUEUE).publish(
            file_bytes,
            headers={
                "filename": data.get("filename"),
                "content-type": data.get("type"),
            },
        )
