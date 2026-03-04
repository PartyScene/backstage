from quart import Quart

import os
import uuid
from datetime import timedelta
from typing import Literal, Sequence, Optional, Dict, Any
import asyncio
import gc
import tempfile
import io

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
register_heif_opener()

from obstore import store
import obstore as obs
from faststream.rabbit import RabbitBroker, RabbitMessage, RabbitQueue
import ormsgpack
from ffmpeg.asyncio import FFmpeg
from ffmpeg.errors import FFmpegError

from shared.utils.obstore import get_obstore

# Compression constants
IMAGE_MAX_DIMENSION = 2048
IMAGE_JPEG_QUALITY = 90
IMAGE_BACKGROUND_COLOR = (255, 255, 255)

VIDEO_MAX_HEIGHT = 1080
VIDEO_MAX_WIDTH = 1920
VIDEO_CRF_QUALITY = 21
VIDEO_MAX_BITRATE = "5M"  # Instagram High Quality target
VIDEO_BUFFER_SIZE = "12M"  # 2x Max Bitrate for handling motion spikes
VIDEO_AUDIO_BITRATE = "128k"  # Instagram standard audio
VIDEO_SAMPLE_RATE = "44100"  # Keep this

URL_EXPIRY_HOURS = 6


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
            self.logger.warning(
                "USING OBS WITH GCS_BUCKET_URI: %s", os.environ["GCS_BUCKET_URI"]
            )

            @self.subscriber(self.RABBITMQ_MEDIA_QUEUE)
            async def handle_media_upload(message: RabbitMessage):
                """Process media upload: fetch from temp, compress, upload to final, cleanup temp."""
                payload = message.body
                # After decode_message, payload is either a dict (new format) or bytes (legacy)
                if isinstance(payload, dict):
                    # New format: message contains source_key and metadata
                    source_key = payload.get("source_key")
                    content_type = payload.get("content_type")
                    filename = payload.get("filename")
                    if not source_key or not content_type:
                        self.logger.error(f"❌ Missing required payload fields: source_key={source_key}, content_type={content_type}")
                        await message.nack(requeue=False)
                        return
                else:
                    # Legacy format: message body is bytes, headers have metadata
                    self.logger.warning("⚠️ Received legacy bytes payload; consider migrating producers")
                    filename = message.headers.get("filename")
                    content_type = message.headers.get("content-type")
                    if not filename or not content_type:
                        self.logger.error(f"❌ Missing required headers: filename={filename}, content_type={content_type}")
                        await message.nack(requeue=False)
                        return
                    # Legacy path: treat bytes directly (no temp staging)
                    file_bytes = payload
                    source_key = None
                
                try:
                    # Fetch bytes from temp store if source_key is present (new path)
                    if source_key:
                        obstore = get_obstore()
                        file_bytes = await obstore.get_temp_bytes(source_key)
                        self.logger.info(f"📥 Fetched from temp: {source_key}")
                    
                    # Compress image or video (GPU/CPU bound - blocking)
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
                    
                    # Determine final destination key
                    if source_key:
                        # New path: write to final bucket
                        # Derive final key from source_key: replace tmp/ prefix with media/
                        dest_key = filename
                        # Ensure extension is normalized (e.g., .mp4 for videos)
                        if not dest_key.lower().endswith('.mp4'):
                            dest_key = os.path.splitext(dest_key)[0] + '.mp4'
                        # Upload to final bucket in background
                        asyncio.create_task(
                            self._background_upload_final(dest_key, content_type, file_bytes, source_key)
                        )
                        self.logger.info(f"📤 Queued final upload: {dest_key}")
                    else:
                        # Legacy path: upload to final bucket directly (no temp cleanup)
                        asyncio.create_task(
                            self._background_upload_legacy(filename, content_type, file_bytes)
                        )
                        self.logger.info(f"📤 Queued legacy upload: {filename}")
                    
                    # Ack immediately after compression (don't wait for upload)
                    await message.ack()
                    
                    # Free memory
                    del file_bytes
                    gc.collect()
                    
                except Exception as e:
                    self.logger.error(f"❌ Processing failed: {filename}: {e}")
                    await message.nack(requeue=False)  # Don't retry encoding failures

    async def decode_message(self, msg: RabbitMessage, original_decoder) -> Optional[RabbitMessage]:
        """Decode RabbitMQ message, trying ormsgpack first, then original decoder."""
        try:
            msg.body = await asyncio.to_thread(ormsgpack.unpackb, msg.body)
            return msg
        except (ormsgpack.MsgpackDecodeError, TypeError, ValueError) as e:
            self.logger.debug(f"ormsgpack decode failed: {e}, trying original decoder")
            try:
                return await original_decoder(msg)
            except Exception as e:
                self.logger.error(f"All decoders failed for message: {e}")
                return None

    async def compress_video(self, input_bytes: bytes, filename: str) -> bytes:
        """Compress video to 720p MP4 with H.264 codec."""
        # Create temp input file
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(filename)[1], delete=False) as temp_input:
            await asyncio.to_thread(temp_input.write, input_bytes)
            temp_input_path = temp_input.name
        
        # Create temp output file (separate file to avoid collision)
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_output:
            temp_output_path = temp_output.name
            # File is auto-closed when exiting context, FFmpeg will write to it
        
        try:
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
                            
                            # NVENC-specific settings - 720p optimized
                            "preset": "p5",              # p5=medium quality/speed
                            "cq": str(VIDEO_CRF_QUALITY),
                            "maxrate": VIDEO_MAX_BITRATE,
                            "bufsize": VIDEO_BUFFER_SIZE,
                            
                            "profile:v": "main",         # Main profile for compatibility
                            "level": "3.1",              # 3.1 for 720p (was 4.1 for 1080p)
                            
                            # Audio settings
                            "codec:a": "aac",
                            "ar": VIDEO_SAMPLE_RATE,
                            "b:a": VIDEO_AUDIO_BITRATE,
                            
                            # Format settings
                            "movflags": "+faststart",
                            "pix_fmt": "yuv420p",
                            
                            # 720p scaling
                            "vf": f"scale_cuda='min({VIDEO_MAX_WIDTH},iw)':'min({VIDEO_MAX_HEIGHT},ih)':force_original_aspect_ratio=decrease"
                        }
                    )
                )
                
                await ffmpeg_hw.execute()
                self.logger.info("✅ Hardware encoding complete")
            
            except FFmpegError as e:
                self.logger.warning(f"⚠️ Hardware failed: {e}, using software")
                
                # Software fallback
                ffmpeg_sw = (
                    FFmpeg()
                    .option("y")
                    .input(temp_input_path)
                    .output(
                        temp_output_path,
                        vcodec="libx264",
                        acodec="aac",
                        preset="slow",
                        profile="high",
                        crf=str(VIDEO_CRF_QUALITY),
                        maxrate=VIDEO_MAX_BITRATE,
                        bufsize=VIDEO_BUFFER_SIZE,
                        level="3.1",
                        ar=VIDEO_SAMPLE_RATE,
                        movflags="+faststart",
                        pix_fmt="yuv420p",
                        vf=f"scale=-2:{VIDEO_MAX_HEIGHT}:flags=lanczos,hqdn3d=1.5:1.5:6:6",
                        threads="0" # Use all available threads
                    )
                )
                await ffmpeg_sw.execute()
                self.logger.info("✅ Software encoding complete")
            
            # Read compressed file
            compressed_bytes = await asyncio.to_thread(
                lambda: open(temp_output_path, 'rb').read()
            )
            
            # Log compression ratio, avoiding division by zero
            if len(compressed_bytes) > 0:
                ratio = len(input_bytes) / len(compressed_bytes)
                self.logger.info(f"Video: {len(input_bytes)} -> {len(compressed_bytes)} bytes ({ratio:.1f}x reduction)")
            else:
                self.logger.warning(f"Video compression resulted in 0 bytes (input: {len(input_bytes)} bytes)")
            
            return compressed_bytes
            
        finally:
            # Clean up temp files
            for path in [temp_input_path, temp_output_path]:
                if os.path.exists(path):
                    await asyncio.to_thread(os.unlink, path)

    async def compress_image(self, image_bytes: bytes) -> bytes:
        """Compress image while preserving quality."""
        try:
            # Wrap entire CPU-bound image processing in to_thread
            def _process_image():
                img = Image.open(io.BytesIO(image_bytes))
                
                # Apply EXIF orientation to prevent rotation issues from phone cameras
                img = ImageOps.exif_transpose(img) or img  # Fallback to original if None
                
                # CRITICAL FIX: Convert ALL non-RGB modes to RGB for maximum Android compatibility
                if img.mode != 'RGB':
                    # Handle transparency modes (RGBA, LA, P with transparency)
                    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                        # Create white background for transparent images
                        background = Image.new('RGB', img.size, IMAGE_BACKGROUND_COLOR)
                        if img.mode == 'RGBA':
                            background.paste(img, mask=img.split()[-1])  # Use alpha as mask
                        elif img.mode == 'LA':
                            background.paste(img, mask=img.split()[-1])  # Use alpha as mask
                        else:  # P mode with transparency
                            background.paste(img)
                        img = background
                    else:
                        # Convert all other modes (CMYK, L, LAB, HSV, YCbCr, etc.) directly to RGB
                        original_mode = img.mode  # Capture mode before conversion
                        img = img.convert('RGB')
                        self.logger.debug(f"Converted {original_mode} image to RGB")
                
                # Resize if too large (max dimension on longest side)
                if max(img.size) > IMAGE_MAX_DIMENSION:
                    ratio = IMAGE_MAX_DIMENSION / max(img.size)
                    new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                
                # Compress with high quality
                output = io.BytesIO()
                # FIX: Remove progressive=True for Android compatibility
                img.save(
                    output, 
                    'JPEG', 
                    quality=IMAGE_JPEG_QUALITY, 
                    optimize=True,
                    progressive=False,  # Better Android compatibility
                    subsampling=0  # Better quality, no chroma subsampling
                )
                return output.getvalue()
            
            compressed_bytes = await asyncio.to_thread(_process_image)
            
            self.logger.info(f"Image compressed: {len(image_bytes)} -> {len(compressed_bytes)} bytes")
            return compressed_bytes
            
        except Exception as e:
            # Fallback: Return original bytes if compression fails
            self.logger.error(f"Image compression failed: {e}, returning original")
            return image_bytes

    async def _background_upload_final(self, dest_key: str, content_type: str, file_bytes: bytes, source_key: str) -> None:
        """Upload compressed file to final bucket and cleanup temp object."""
        try:
            obstore = get_obstore()
            await obstore.put_final_bytes(dest_key, file_bytes, content_type)
            self.logger.info(f"✅ Final upload complete: {dest_key} ({len(file_bytes)} bytes)")
            
            # Cleanup temp object on success
            try:
                await obstore.delete_temp(source_key)
                self.logger.info(f"🗑️ Cleaned temp: {source_key}")
            except Exception as cleanup_err:
                self.logger.warning(f"⚠️ Failed to cleanup temp {source_key}: {cleanup_err}")
            
        except Exception as e:
            self.logger.error(f"❌ Final upload failed for {dest_key} (type: {content_type}, size: {len(file_bytes)} bytes): {e}")
            # TODO: Implement retry logic or dead letter queue
            
        finally:
            # Free memory after upload
            del file_bytes
            gc.collect()

    async def _background_upload_legacy(self, filename: str, content_type: str, file_bytes: bytes) -> None:
        """Legacy upload path: directly to final bucket (no temp staging)."""
        try:
            await obs.put_async(
                self.OBS_STORE,
                filename,
                file_bytes,
                attributes={"Content-Type": content_type},
            )
            self.logger.info(f"✅ Legacy upload complete: {filename} ({len(file_bytes)} bytes)")
            
        except Exception as e:
            self.logger.error(f"❌ Legacy upload failed for {filename} (type: {content_type}, size: {len(file_bytes)} bytes): {e}")
            # TODO: Implement retry logic or dead letter queue
            
        finally:
            # Free memory after upload
            del file_bytes
            gc.collect()

    async def sign_put_urls(self, filenames: Sequence[str]) -> list:
        signed_urls = await obs.sign_async(
            self.OBS_STORE,
            "PUT",
            filenames,
            timedelta(hours=URL_EXPIRY_HOURS),
        )
        return signed_urls

    async def _publish_r18e(
        self, filename: str, file: Any, content_type: Literal["MEDIA", "POST", "EVENT"]
    ) -> None:
        """Publish file to R18E (content moderation) queue."""
        if not isinstance(file, bytes):
            file_data = await asyncio.to_thread(file.read)
            file_bytes = await asyncio.to_thread(ormsgpack.packb, file_data)
        else:
            file_bytes = await asyncio.to_thread(ormsgpack.packb, file)
        
        await self.publisher(self.RABBITMQ_R18E_QUEUE).publish(
            file_bytes,
            headers={"type": content_type, "filename": filename},
        )

    async def _publish_media(self, data: Dict[str, str], file: io.BytesIO) -> None:
        """
        Publish a message to the media queue for processing.
        
        New flow: upload file bytes to temp bucket, then enqueue a small message with the temp key.
        Legacy fallback: if temp bucket is not configured, send bytes directly (old behavior).
        """
        # Snapshot values immediately to prevent race conditions
        filename = data.get("filename")
        content_type = data.get("type")
        
        if not filename or not content_type:
            self.logger.error(f"Missing required data: filename={filename}, type={content_type}")
            return
        
        try:
            obstore = get_obstore()
            # Generate a temp key with tmp/ prefix
            temp_key = f"tmp/{filename}"
            
            # Read file bytes and upload to temp bucket
            file_bytes = await asyncio.to_thread(file.read)
            await obstore.put_temp_bytes(temp_key, file_bytes, content_type)
            self.logger.info(f"📤 Staged to temp: {temp_key} ({len(file_bytes)} bytes)")
            
            # Prepare message payload with reference to temp object (no bytes)
            payload = {
                "source_key": temp_key,
                "content_type": content_type,
                "filename": filename,
                # Include any other metadata the worker might need
                "creator": data.get("creator"),
                "post_id": data.get("post_id"),
                "media_id": data.get("media_id"),
                "event_id": data.get("event_id"),
                "context": data.get("context"),
            }
            # Remove None values to keep payload clean
            payload = {k: v for k, v in payload.items() if v is not None}
            
            # Publish the reference message (msgpacked dict)
            payload_bytes = await asyncio.to_thread(ormsgpack.packb, payload)
            await self.publisher(self.RABBITMQ_MEDIA_QUEUE).publish(payload_bytes)
            self.logger.info(f"📬 Enqueued media task: {temp_key}")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to stage and enqueue media {filename}: {e}")
            # Optional: fallback to legacy bytes payload if temp staging fails
            try:
                self.logger.warning("⚠️ Falling back to legacy bytes payload")
                file_bytes = await asyncio.to_thread(file.read)
                file_bytes_packed = await asyncio.to_thread(ormsgpack.packb, file_bytes)
                await self.publisher(self.RABBITMQ_MEDIA_QUEUE).publish(
                    file_bytes_packed,
                    headers={
                        "filename": filename,
                        "content-type": content_type,
                    },
                )
                self.logger.info(f"📬 Enqueued legacy media task: {filename}")
            except Exception as fallback_err:
                self.logger.error(f"❌ Legacy fallback also failed for {filename}: {fallback_err}")