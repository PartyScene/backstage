from quart import Quart

import os
import json
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
VIDEO_MAX_BITRATE = "5M"
VIDEO_BUFFER_SIZE = "12M"
VIDEO_AUDIO_BITRATE = "128k"
VIDEO_SAMPLE_RATE = "44100"

URL_EXPIRY_HOURS = 6


class RMQBroker(RabbitBroker):

    def __init__(self, app: Quart, *args, **kwargs):
        self.RABBITMQ_MEDIA_QUEUE = RabbitQueue(os.environ["RABBITMQ_MEDIA_QUEUE"])
        self.RABBITMQ_R18E_QUEUE = RabbitQueue(os.environ["RABBITMQ_R18E_QUEUE"])
        self.OBS_STORE = store.GCSStore(os.environ["GCS_BUCKET_NAME"])

        self.logger = app.logger
        self.conn = app.conn  # MediaDB instance

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
                """Process media upload: fetch from temp, compress, extract metadata, upload to final."""
                payload = message.body

                if isinstance(payload, dict):
                    source_key  = payload.get("source_key")
                    content_type = payload.get("content_type")
                    filename    = payload.get("filename")
                    media_id    = payload.get("media_id")
                    if not source_key or not content_type:
                        self.logger.error(
                            f"❌ Missing required payload fields: "
                            f"source_key={source_key}, content_type={content_type}"
                        )
                        await message.nack(requeue=False)
                        return
                else:
                    self.logger.warning("⚠️ Received legacy bytes payload; consider migrating producers")
                    filename     = message.headers.get("filename")
                    content_type = message.headers.get("content-type")
                    media_id     = message.headers.get("media_id")
                    if not filename or not content_type:
                        self.logger.error(
                            f"❌ Missing required headers: "
                            f"filename={filename}, content_type={content_type}"
                        )
                        await message.nack(requeue=False)
                        return
                    file_bytes = payload
                    source_key = None

                try:
                    if source_key:
                        obstore = get_obstore()
                        file_bytes = await obstore.get_temp_bytes(source_key)
                        self.logger.info(f"📥 Fetched from temp: {source_key}")

                    # ── Compress ──────────────────────────────────────────────
                    if content_type.startswith('image/'):
                        file_bytes = await self.compress_image(file_bytes)
                        self.logger.info(f"✅ Compressed image: {filename}")
                        metadata = await self.extract_image_metadata(file_bytes, filename, content_type)

                    elif content_type.startswith('video/'):
                        file_bytes = await self.compress_video(file_bytes, filename)
                        if not filename.lower().endswith('.mp4'):
                            filename = os.path.splitext(filename)[0] + '.mp4'
                            content_type = 'video/mp4'
                        self.logger.info(f"✅ Compressed video: {filename}")
                        metadata = await self.extract_video_metadata(file_bytes, filename)

                    else:
                        metadata = None

                    # ── Upload (background) ───────────────────────────────────
                    if source_key:
                        dest_key = filename
                        asyncio.create_task(
                            self._background_upload_final(
                                dest_key, content_type, file_bytes, source_key, media_id, metadata
                            )
                        )
                        self.logger.info(f"📤 Queued final upload: {dest_key}")
                    else:
                        asyncio.create_task(
                            self._background_upload_legacy(
                                filename, content_type, file_bytes, media_id, metadata
                            )
                        )
                        self.logger.info(f"📤 Queued legacy upload: {filename}")

                    await message.ack()

                    del file_bytes
                    gc.collect()

                except Exception as e:
                    self.logger.error(f"❌ Processing failed: {filename}: {e}")
                    await message.nack(requeue=False)

    # -------------------------------------------------------------------------
    # Metadata extraction
    # -------------------------------------------------------------------------

    async def extract_video_metadata(self, video_bytes: bytes, filename: str) -> Dict[str, Any]:
        """
        Run ffprobe on compressed video bytes using ffmpeg.asyncio and return
        a structured metadata dict with basic + extended fields.
        """
        suffix = os.path.splitext(filename)[1] or '.mp4'

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            await asyncio.to_thread(tmp.write, video_bytes)
            tmp_path = tmp.name

        try:
            ffprobe = (
                FFmpeg(executable="ffprobe")
                .input(
                    tmp_path,
                    print_format="json",
                    show_format=None,
                    show_streams=None,
                )
            )

            raw_output = await ffprobe.execute()
            raw = json.loads(raw_output)
            metadata = self._parse_video_metadata(raw, filename)
            self.logger.info(f"📐 Video metadata extracted: {filename}")
            return metadata

        except Exception as e:
            self.logger.error(f"❌ ffprobe failed for {filename}: {e}")
            return {}

        finally:
            if os.path.exists(tmp_path):
                await asyncio.to_thread(os.unlink, tmp_path)

    def _parse_video_metadata(self, raw: Dict, filename: str) -> Dict[str, Any]:
        """Parse raw ffprobe JSON into a clean, flat metadata dict."""
        fmt     = raw.get("format", {})
        streams = raw.get("streams", [])

        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

        def parse_fraction(value: Optional[str]) -> Optional[float]:
            """Convert ffprobe fraction strings like '30000/1001' to a float."""
            if not value:
                return None
            try:
                parts = value.split("/")
                return round(int(parts[0]) / int(parts[1]), 3) if len(parts) == 2 else float(value)
            except (ValueError, ZeroDivisionError):
                return None

        def to_int(value) -> Optional[int]:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        metadata = {
            # ── Container ────────────────────────────────────────────────────
            "filename":           filename,
            "format_name":        fmt.get("format_name"),
            "format_long_name":   fmt.get("format_long_name"),
            "duration_seconds":   float(fmt["duration"]) if fmt.get("duration") else None,
            "size_bytes":         to_int(fmt.get("size")),
            "overall_bitrate":    to_int(fmt.get("bit_rate")),

            # ── Video stream ─────────────────────────────────────────────────
            "video_codec":        video_stream.get("codec_name"),
            "video_codec_long":   video_stream.get("codec_long_name"),
            "video_profile":      video_stream.get("profile"),
            "width":              video_stream.get("width"),
            "height":             video_stream.get("height"),
            "pixel_format":       video_stream.get("pix_fmt"),
            "color_space":        video_stream.get("color_space"),
            "color_primaries":    video_stream.get("color_primaries"),
            "color_transfer":     video_stream.get("color_transfer"),
            "video_bitrate":      to_int(video_stream.get("bit_rate")),
            "frame_rate":         parse_fraction(video_stream.get("r_frame_rate")),
            "avg_frame_rate":     parse_fraction(video_stream.get("avg_frame_rate")),
            "nb_frames":          to_int(video_stream.get("nb_frames")),
            "video_duration":     float(video_stream["duration"]) if video_stream.get("duration") else None,

            # ── Audio stream ─────────────────────────────────────────────────
            "audio_codec":           audio_stream.get("codec_name"),
            "audio_codec_long":      audio_stream.get("codec_long_name"),
            "audio_bitrate":         to_int(audio_stream.get("bit_rate")),
            "audio_channels":        audio_stream.get("channels"),
            "audio_channel_layout":  audio_stream.get("channel_layout"),
            "sample_rate":           to_int(audio_stream.get("sample_rate")),
            "audio_duration":        float(audio_stream["duration"]) if audio_stream.get("duration") else None,
        }

        # Strip None values — SurrealDB doesn't need null fields
        return {k: v for k, v in metadata.items() if v is not None}

    async def extract_image_metadata(
        self, image_bytes: bytes, filename: str, content_type: str
    ) -> Dict[str, Any]:
        """
        Extract metadata from a compressed image using Pillow.
        Mirrors the video metadata schema where fields overlap.
        """
        def _read():
            img = Image.open(io.BytesIO(image_bytes))
            return {
                "filename":    filename,
                "format_name": img.format or content_type.split("/")[-1].upper(),
                "width":       img.width,
                "height":      img.height,
                "color_space": img.mode,
                "size_bytes":  len(image_bytes),
            }

        try:
            metadata = await asyncio.to_thread(_read)
            self.logger.info(f"📐 Image metadata extracted: {filename}")
            return metadata
        except Exception as e:
            self.logger.error(f"❌ Image metadata extraction failed for {filename}: {e}")
            return {}

    # -------------------------------------------------------------------------
    # Metadata persistence
    # -------------------------------------------------------------------------

    async def _store_metadata(self, media_id: str, metadata: Dict[str, Any]) -> None:
        """
        Persist ffprobe/Pillow metadata to SurrealDB via MediaDB.update_media_metadata.
        Best-effort: logs failures but never raises so the upload path is not blocked.
        """
        if not metadata or not media_id:
            return

        try:
            await self.conn.update_media_metadata(media_id, metadata)
            self.logger.info(f"✅ Metadata stored for media_id={media_id}")
        except Exception as e:
            self.logger.error(f"❌ Metadata storage failed for media_id={media_id}: {e}")

    # -------------------------------------------------------------------------
    # Upload helpers
    # -------------------------------------------------------------------------

    async def _background_upload_final(
        self,
        dest_key: str,
        content_type: str,
        file_bytes: bytes,
        source_key: str,
        media_id: Optional[str],
        metadata: Optional[Dict[str, Any]],
    ) -> None:
        """Upload compressed file to final bucket, cleanup temp, then store metadata."""
        try:
            obstore = get_obstore()
            await obstore.put_final_bytes(dest_key, file_bytes, content_type)
            self.logger.info(f"✅ Final upload complete: {dest_key} ({len(file_bytes)} bytes)")

            try:
                await obstore.delete_temp(source_key)
                self.logger.info(f"🗑️ Cleaned temp: {source_key}")
            except Exception as cleanup_err:
                self.logger.warning(f"⚠️ Failed to cleanup temp {source_key}: {cleanup_err}")

        except Exception as e:
            self.logger.error(
                f"❌ Final upload failed for {dest_key} "
                f"(type: {content_type}, size: {len(file_bytes)} bytes): {e}"
            )
        finally:
            del file_bytes
            gc.collect()

        # Store metadata after upload — best-effort, non-blocking
        if media_id and metadata:
            await self._store_metadata(media_id, metadata)

    async def _background_upload_legacy(
        self,
        filename: str,
        content_type: str,
        file_bytes: bytes,
        media_id: Optional[str],
        metadata: Optional[Dict[str, Any]],
    ) -> None:
        """Legacy upload path: directly to final bucket, then store metadata."""
        try:
            await obs.put_async(
                self.OBS_STORE,
                filename,
                file_bytes,
                attributes={"Content-Type": content_type},
            )
            self.logger.info(f"✅ Legacy upload complete: {filename} ({len(file_bytes)} bytes)")

        except Exception as e:
            self.logger.error(
                f"❌ Legacy upload failed for {filename} "
                f"(type: {content_type}, size: {len(file_bytes)} bytes): {e}"
            )
        finally:
            del file_bytes
            gc.collect()

        # Store metadata after upload — best-effort, non-blocking
        if media_id and metadata:
            await self._store_metadata(media_id, metadata)

    # -------------------------------------------------------------------------
    # Compression
    # -------------------------------------------------------------------------

    async def compress_video(self, input_bytes: bytes, filename: str) -> bytes:
        """Compress video to 1080p MP4 with H.264 codec."""
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(filename)[1], delete=False) as temp_input:
            await asyncio.to_thread(temp_input.write, input_bytes)
            temp_input_path = temp_input.name

        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_output:
            temp_output_path = temp_output.name

        try:
            try:
                ffmpeg_hw = (
                    FFmpeg()
                    .option("y")
                    .option("hwaccel", "cuda")
                    .option("hwaccel_output_format", "cuda")
                    .input(temp_input_path)
                    .output(
                        temp_output_path,
                        {
                            "codec:v": "h264_nvenc",
                            "preset": "p5",
                            "cq": str(VIDEO_CRF_QUALITY),
                            "maxrate": VIDEO_MAX_BITRATE,
                            "bufsize": VIDEO_BUFFER_SIZE,
                            "profile:v": "main",
                            "level": "3.1",
                            "codec:a": "aac",
                            "ar": VIDEO_SAMPLE_RATE,
                            "b:a": VIDEO_AUDIO_BITRATE,
                            "movflags": "+faststart",
                            "pix_fmt": "yuv420p",
                            "vf": f"scale_cuda='min({VIDEO_MAX_WIDTH},iw)':'min({VIDEO_MAX_HEIGHT},ih)':force_original_aspect_ratio=decrease"
                        }
                    )
                )
                await ffmpeg_hw.execute()
                self.logger.info("✅ Hardware encoding complete")

            except FFmpegError as e:
                self.logger.warning(f"⚠️ Hardware failed: {e}, using software")
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
                        threads="0"
                    )
                )
                await ffmpeg_sw.execute()
                self.logger.info("✅ Software encoding complete")

            compressed_bytes = await asyncio.to_thread(
                lambda: open(temp_output_path, 'rb').read()
            )

            if len(compressed_bytes) > 0:
                ratio = len(input_bytes) / len(compressed_bytes)
                self.logger.info(f"Video: {len(input_bytes)} -> {len(compressed_bytes)} bytes ({ratio:.1f}x reduction)")
            else:
                self.logger.warning(f"Video compression resulted in 0 bytes (input: {len(input_bytes)} bytes)")

            return compressed_bytes

        finally:
            for path in [temp_input_path, temp_output_path]:
                if os.path.exists(path):
                    await asyncio.to_thread(os.unlink, path)

    async def compress_image(self, image_bytes: bytes) -> bytes:
        """Compress image while preserving quality."""
        try:
            def _process_image():
                img = Image.open(io.BytesIO(image_bytes))
                img = ImageOps.exif_transpose(img) or img

                if img.mode != 'RGB':
                    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                        background = Image.new('RGB', img.size, IMAGE_BACKGROUND_COLOR)
                        if img.mode == 'RGBA':
                            background.paste(img, mask=img.split()[-1])
                        elif img.mode == 'LA':
                            background.paste(img, mask=img.split()[-1])
                        else:
                            background.paste(img)
                        img = background
                    else:
                        original_mode = img.mode
                        img = img.convert('RGB')
                        self.logger.debug(f"Converted {original_mode} image to RGB")

                if max(img.size) > IMAGE_MAX_DIMENSION:
                    ratio = IMAGE_MAX_DIMENSION / max(img.size)
                    new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)

                output = io.BytesIO()
                img.save(
                    output,
                    'JPEG',
                    quality=IMAGE_JPEG_QUALITY,
                    optimize=True,
                    progressive=False,
                    subsampling=0
                )
                return output.getvalue()

            compressed_bytes = await asyncio.to_thread(_process_image)
            self.logger.info(f"Image compressed: {len(image_bytes)} -> {len(compressed_bytes)} bytes")
            return compressed_bytes

        except Exception as e:
            self.logger.error(f"Image compression failed: {e}, returning original")
            return image_bytes

    # -------------------------------------------------------------------------
    # Decoding / signing / publishing (unchanged)
    # -------------------------------------------------------------------------

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
        Legacy fallback: send bytes directly if temp staging fails.
        """
        filename     = data.get("filename")
        content_type = data.get("type")

        if not filename or not content_type:
            self.logger.error(f"Missing required data: filename={filename}, type={content_type}")
            return

        try:
            obstore  = get_obstore()
            temp_key = f"tmp/{filename}"

            file_bytes = await asyncio.to_thread(file.read)
            await obstore.put_temp_bytes(temp_key, file_bytes, content_type)
            self.logger.info(f"📤 Staged to temp: {temp_key} ({len(file_bytes)} bytes)")

            payload = {
                "source_key":  temp_key,
                "content_type": content_type,
                "filename":    filename,
                "creator":     data.get("creator"),
                "post_id":     data.get("post_id"),
                "media_id":    data.get("media_id"),
                "event_id":    data.get("event_id"),
                "context":     data.get("context"),
            }
            payload = {k: v for k, v in payload.items() if v is not None}

            payload_bytes = await asyncio.to_thread(ormsgpack.packb, payload)
            await self.publisher(self.RABBITMQ_MEDIA_QUEUE).publish(payload_bytes)
            self.logger.info(f"📬 Enqueued media task: {temp_key}")

        except Exception as e:
            self.logger.error(f"❌ Failed to stage and enqueue media {filename}: {e}")
            try:
                self.logger.warning("⚠️ Falling back to legacy bytes payload")
                file_bytes = await asyncio.to_thread(file.read)
                file_bytes_packed = await asyncio.to_thread(ormsgpack.packb, file_bytes)
                await self.publisher(self.RABBITMQ_MEDIA_QUEUE).publish(
                    file_bytes_packed,
                    headers={
                        "filename":      filename,
                        "content-type":  content_type,
                    },
                )
                self.logger.info(f"📬 Enqueued legacy media task: {filename}")
            except Exception as fallback_err:
                self.logger.error(f"❌ Legacy fallback also failed for {filename}: {fallback_err}")