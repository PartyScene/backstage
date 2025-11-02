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
import asyncio
import gc

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
            async def handle_media_upload(message: RabbitMessage):
                """Process media upload: compress, then upload in background"""
                filename = message.headers.get("filename")
                content_type = message.headers.get("content-type")
                
                try:
                    # Compress image or video (GPU/CPU bound - blocking)
                    file_bytes = message.body
                    
                    if content_type.startswith('image/'):
                        file_bytes = await self.compress_image(file_bytes)
                        self.logger.info(f"✅ Compressed image: {filename}")
                    
                    elif content_type.startswith('video/'):
                        file_bytes = await self.compress_video(file_bytes, filename)
                        # Update filename and content type to MP4
                        if not filename.lower().endswith('.mp4'):
                            filename = os.path.splitext(filename)[0] + '.mp4'
                            content_type = 'video/mp4'
                        self.logger.info(f"✅ Compressed video: {filename}")
                    
                    # Upload in background (network bound - non-blocking)
                    asyncio.create_task(
                        self._background_upload(filename, content_type, file_bytes)
                    )
                    
                    # Ack immediately after compression (don't wait for upload)
                    await message.ack()
                    self.logger.info(f"📤 Queued upload: {filename}")
                    
                    # Free memory
                    del message.body
                    gc.collect()
                    
                except Exception as e:
                    self.logger.error(f"❌ Processing failed: {filename}: {e}")
                    await message.nack(requeue=False)  # Don't retry encoding failures

    async def decode_message(self, msg: RabbitMessage, original_decoder):
        """Decode message with fallback handling and proper error logging."""
        try:
            msg.body = ormsgpack.unpackb(msg.body)
            return msg
        except (ormsgpack.MsgpackDecodeError, ValueError, TypeError) as e:
            self.logger.warning(f"ormsgpack decode failed: {e}, trying original decoder")
            try:
                return await original_decoder(msg)
            except Exception as e:
                self.logger.error(f"All decoders failed for message: {e}")
                raise ValueError(f"Unable to decode message: {e}") from e

    async def compress_video(self, input_bytes: bytes, filename: str) -> bytes:
        """Compress video with optimized settings for size reduction while preserving quality"""
        import tempfile
        from ffmpeg.asyncio import FFmpeg
        from ffmpeg.errors import FFmpegError
        
        # Load configurable settings
        max_bitrate = os.getenv("VIDEO_MAX_BITRATE", "5M")
        cq_value = os.getenv("VIDEO_CQ_VALUE", "23")  # Instagram-level quality (lower = better)
        audio_bitrate = os.getenv("AUDIO_BITRATE", "96k")
        
        # Create input temp file with unique name to prevent race conditions
        temp_input_fd, temp_input_path = tempfile.mkstemp(suffix=os.path.splitext(filename)[1])
        # Generate unique output path but don't create file - let FFmpeg create it to avoid permission issues
        temp_output_path = tempfile.mktemp(suffix='.mp4')
        
        try:
            # Write input to temp file and close descriptor
            os.write(temp_input_fd, input_bytes)
            os.close(temp_input_fd)
            # Try hardware acceleration first (NVIDIA)
            # try:
            #     ffmpeg_hw = (
            #         FFmpeg()
            #         .option("y")  # Overwrite output file
            #         .option("hwaccel", "cuda")  # Hardware acceleration
            #         .input(temp_input_path)
            #         .output(
            #             temp_output_path,
            #             {
            #                 "codec:v": "h264_nvenc",     # NVIDIA hardware encoder
            #                 "preset": "slow",            # Better compression than "fast"
            #                 "crf": "28",                 # More aggressive compression (was 23)
            #                 "maxrate": "5M",             # 5Mbps max bitrate
            #                 "bufsize": "10M",            # Buffer size
            #                 "profile:v": "high",         # Better quality than baseline
            #                 "level": "4.0",              # Support higher resolutions
            #                 "codec:a": "aac",            # AAC audio
            #                 "ar": "44100",               # Standard audio sample rate
            #                 "b:a": "128k",               # Audio bitrate 128k
            #                 "movflags": "+faststart",    # Enable progressive download
            #                 "pix_fmt": "yuv420p",        # Compatible pixel format
            #                 "vf": "scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"  # Scale down to 1080p max
            #             }
            #         )
            #     )
                
            #     await ffmpeg_hw.execute()
            #     self.logger.info("Successfully compressed video using hardware acceleration")
                
            # except FFmpegError as e:
            #     self.logger.info(f"Hardware acceleration unavailable, using software: {e}")
                
            #     # Fall back to software encoding
            #     ffmpeg_sw = (
            #         FFmpeg()
            #         .option("y")  # Overwrite output file
            #         .input(temp_input_path)
            #         .output(
            #             temp_output_path,
            #             {
            #                 "codec:v": "libx264",        # H.264 codec for compatibility
            #                 "preset": "slow",            # Better compression than "fast"
            #                 "crf": "28",                 # More aggressive compression (was 23)
            #                 "maxrate": "5M",             # 5Mbps max bitrate
            #                 "bufsize": "10M",            # Buffer size
            #                 "profile:v": "high",         # Better quality than baseline
            #                 "level": "4.0",              # Support higher resolutions
            #                 "codec:a": "aac",            # AAC audio
            #                 "ar": "44100",               # Standard audio sample rate
            #                 "b:a": "128k",               # Audio bitrate 128k
            #                 "movflags": "+faststart",    # Enable progressive download
            #                 "pix_fmt": "yuv420p",        # Compatible pixel format
            #                 "vf": "scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"  # Scale down to 1080p max
            #             }
            #         )
            #     )
                
            #     await ffmpeg_sw.execute()
            #     self.logger.info("Successfully compressed video using software encoding")
            

            try:
                ffmpeg_hw = (
                    FFmpeg()
                    .option("y")
                    .option("hwaccel", "cuda")
                    .option("hwaccel_output_format", "cuda")  # Keep frames on GPU
                    .input(temp_input_path)
                    .output(
                        temp_output_path,
                        {
                            "codec:v": "h264_nvenc",
                            
                            # NVENC-specific settings (different from libx264!)
                            "preset": "p5",              # p1-p7, p5=medium quality/speed
                            "tune": "hq",                # High quality mode
                            "rc": "vbr",                 # Variable bitrate (better than CQ for NVENC)
                            "cq": cq_value,              # Configurable quality level
                            "b:v": "0",                  # Let cq control quality
                            "maxrate": max_bitrate,      # Configurable max bitrate
                            "bufsize": "10M",            # 2x maxrate recommended
                            
                            # GOP settings for better seeking/scrubbing
                            "g": "48",                   # 2-second GOP at 24fps (Instagram standard)
                            "keyint_min": "48",          # Enforce consistent keyframe interval
                            
                            "profile:v": "main",         # 'main' better than 'high' for mobile
                            "level": "4.1",              # 4.1 for 1080p60 support
                            "spatial-aq": "1",           # Spatial adaptive quantization
                            "temporal-aq": "1",          # Temporal adaptive quantization
                            "rc-lookahead": "32",        # Lookahead frames for better decisions
                            
                            # Audio settings
                            "codec:a": "aac",
                            "ar": "44100",
                            "b:a": audio_bitrate,        # Configurable audio bitrate
                            
                            # Format settings
                            "movflags": "+faststart",
                            "pix_fmt": "yuv420p",
                            
                            # Scaling (fixed - removed forced padding)
                            "vf": "scale_cuda='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease"
                        }
                    )
                )
                
                await ffmpeg_hw.execute()
                self.logger.info("✅ Hardware acceleration: Video compressed successfully")
            
            except FFmpegError as e:
                self.logger.warning(f"⚠️ Hardware acceleration failed: {e}")
                self.logger.info("Falling back to software encoding...")
                
                # ============================================
                # SOFTWARE FALLBACK (libx264)
                # ============================================
                try:
                    ffmpeg_sw = (
                        FFmpeg()
                        .option("y")
                        .input(temp_input_path)
                        .output(
                            temp_output_path,
                            {
                                "codec:v": "libx264",
                                
                                # libx264-specific settings
                                "preset": "medium",          # Faster than 'slow', minimal quality loss
                                "crf": cq_value,             # Configurable quality-based encoding
                                # Note: removed maxrate/bufsize - let CRF work alone
                                
                                # GOP settings for better seeking/scrubbing
                                "g": "48",                   # 2-second GOP at 24fps (Instagram standard)
                                "keyint_min": "48",          # Enforce consistent keyframe interval
                                "sc_threshold": "0",         # Disable scene detection for consistency
                                
                                "profile:v": "main",         # Better mobile support
                                "level": "4.1",              # 1080p60 support
                                "tune": "film",              # Better for real-world content
                                
                                # x264 optimization flags
                                "x264-params": "ref=4:bframes=3:b-adapt=2:direct=auto:me=umh:subme=7:trellis=1:rc-lookahead=50",
                                
                                # Audio settings
                                "codec:a": "aac",
                                "ar": "44100",
                                "b:a": audio_bitrate,        # Configurable audio bitrate
                                
                                # Format settings
                                "movflags": "+faststart",
                                "pix_fmt": "yuv420p",
                                
                                # Scaling (fixed - removed forced padding)
                                "vf": "scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease"
                            }
                        )
                    )
                    
                    await ffmpeg_sw.execute()
                    self.logger.info("✅ Software encoding: Video compressed successfully")
                    
                except FFmpegError as e:
                    self.logger.error(f"❌ Software encoding failed: {e}")
                    raise

            # Read compressed file
            with open(temp_output_path, 'rb') as f:
                compressed_bytes = f.read()
                
            self.logger.info(f"Video compressed: {len(input_bytes)} -> {len(compressed_bytes)} bytes ({filename})")
            
            # Free input memory before returning
            del input_bytes # noqa: F841 free memory
            
            return compressed_bytes
            
        finally:
            # Clean up temp files
            for path in [temp_input_path, temp_output_path]:
                if os.path.exists(path):
                    os.unlink(path)
            
            # Force garbage collection after video processing
            collected = gc.collect()
            if collected > 0:
                self.logger.debug(f"GC collected {collected} objects")

    async def compress_image(self, image_bytes: bytes) -> bytes:
        """Compress image while preserving quality"""
        # Load configurable settings
        max_dimension = int(os.getenv("IMAGE_MAX_DIMENSION", "2048"))
        jpeg_quality = int(os.getenv("IMAGE_JPEG_QUALITY", "90"))
        
        img = Image.open(io.BytesIO(image_bytes))
        
        # Convert to RGB if necessary (for JPEG compatibility)
        if img.mode in ('RGBA', 'LA', 'P'):
            # Create white background for transparent images
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                background.paste(img, mask=img.split()[-1])  # Use alpha as mask
            else:
                background.paste(img)
            img = background
        
        # Resize if too large
        if max(img.size) > max_dimension:
            ratio = max_dimension / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Compress with configurable quality
        output = io.BytesIO()
        img.save(output, 'JPEG', quality=jpeg_quality, optimize=True, progressive=True)
        compressed_bytes = output.getvalue()
        
        self.logger.info(f"Image compressed: {len(image_bytes)} -> {len(compressed_bytes)} bytes")
        
        # Free input memory
        del image_bytes
        gc.collect()
        
        return compressed_bytes

    async def _background_upload(self, filename: str, content_type: str, file_bytes: bytes):
        """Upload file to GCS in the background without blocking the queue"""
        import obstore as obs
        
        try:
            await obs.put_async(
                self.OBS_STORE,
                filename,
                file_bytes,
                attributes={"Content-Type": content_type},
            )
            self.logger.info(f"✅ Upload complete: {filename} ({len(file_bytes)} bytes)")
            
        except Exception as e:
            self.logger.error(f"❌ Upload failed: {filename}: {e}")
            # TODO: Implement retry logic or dead letter queue
            
        finally:
            # Free memory after upload
            del file_bytes
            gc.collect()
    
    async def upload_to_bucket(self, data, file_bytes: bytes):
        """Legacy method - kept for compatibility. New code uses _background_upload."""
        import obstore as obs
        
        filename = data["filename"]
        content_type = data["content-type"]
        
        # Compress images
        if content_type.startswith('image/'):
            try:
                file_bytes = await self.compress_image(file_bytes)
                self.logger.info(f"Compressed image: {filename}")
            except Exception as e:
                self.logger.error(f"Failed to compress image {filename}: {e}")
        
        # Compress videos (convert MOV to MP4 and optimize all videos)
        if content_type.startswith('video/'):
            try:
                file_bytes = await self.compress_video(file_bytes, filename)
                if not filename.lower().endswith('.mp4'):
                    data["filename"] = os.path.splitext(filename)[0] + '.mp4'
                    data["content-type"] = 'video/mp4'
                    self.logger.info(f"Converted video to MP4: {filename} -> {data['filename']}")
                else:
                    self.logger.info(f"Compressed video: {filename}")
            except Exception as e:
                self.logger.error(f"Failed to process video {filename}: {e}")
        
        await obs.put_async(
            self.OBS_STORE,
            data["filename"],
            file_bytes,
            attributes={"Content-Type": data["content-type"]},
        )
        
        # Free memory
        del file_bytes
        gc.collect()

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
        # Snapshot values immediately to prevent race conditions
        filename = data.get("filename")
        content_type = data.get("type")
        
        file_bytes: bytes = ormsgpack.packb(file.read())
        await self.publisher(self.RABBITMQ_MEDIA_QUEUE).publish(
            file_bytes,
            headers={
                "filename": filename,
                "content-type": content_type,
            },
        )
