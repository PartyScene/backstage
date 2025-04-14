from quart import current_app as app, request, jsonify, logging
from quart.datastructures import FileStorage
from quart_jwt_extended import jwt_required, get_jwt_identity
from google.cloud import storage
from datetime import timedelta
import werkzeug.datastructures

from shared.classful import route, QuartClassful
from media.src.connectors import MediaDB
from http import HTTPStatus

import os
import io
import werkzeug
from datetime import datetime, timedelta
from aiocache import cached

from obstore.store import GCSStore
import obstore as obs


class BaseView(QuartClassful):

    def __init__(self):
        self.GCP_client = storage.Client(os.getenv("GOOGLE_CLOUD_PROJECT"))
        self.bucket = self.GCP_client.bucket(os.getenv("GCS_BUCKET_NAME"))
        # Try something new
        self.OBS_STORE = GCSStore(os.environ["GCS_BUCKET_NAME"])
        self.logger = logging.create_logger(app)
        self.redis = app.redis
        self.__media_handler: MediaDB = app.conn

    async def upload_to_bucket(self, filename, image_bytes: bytes):
        await obs.put_async(self.OBS_STORE, filename, image_bytes)

    @route("/", methods=["GET"])
    async def index(self):
        return await self.healthcheck()

    @route("/media/health", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def healthcheck(self):
        """
        Simple health check endpoint that verifies service and dependency status.
        Returns 200 OK if everything is healthy, 503 Service Unavailable otherwise.
        """
        health_status = {
            "service": "microservices.media",
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "dependencies": {"database": "unknown", "redis": "unknown"},
        }

        # Check database connection
        try:
            db_info = await self.__media_handler._info()
            health_status["dependencies"]["database"] = "healthy"
        except Exception as e:
            self.logger.error(f"Database health check failed: {e}")
            health_status["dependencies"]["database"] = "unhealthy"
            health_status["status"] = "degraded"

        # Check Redis connection
        try:
            redis_ping = await self.redis.ping()
            health_status["dependencies"]["redis"] = (
                "healthy" if redis_ping else "unhealthy"
            )
            if not redis_ping:
                health_status["status"] = "degraded"
        except Exception as e:
            self.logger.error(f"Redis health check failed: {e}")
            health_status["dependencies"]["redis"] = "unhealthy"
            health_status["status"] = "degraded"

        status_code = (
            HTTPStatus.OK
            if health_status["status"] == "healthy"
            else HTTPStatus.SERVICE_UNAVAILABLE
        )

        return jsonify(health_status), status_code

    # @route("/media/upload", methods=["GET", "POST"])
    # @jwt_required
    # async def upload(self):
    #     """Upload a media type to our GCP Bucket"""
    #     ...
    #     file: werkzeug.datastructures.FileStorage = (await request.files).get("file")

    #     # Get the data and attach fields
    #     data = await request.form
    #     data = data.to_dict()
    #     data["creator"] = get_jwt_identity()
    #     data["filename"] = file.filename

    #     # Upload to GCP
    #     file.stream.seek(0) # Reset the stream position
    #     await obs.put_async(self.OBS_STORE, file.filename, file.stream)

    #     # data["url"] = await obs.sign_async(
    #     #     self.OBS_STORE, "GET", file.filename, timedelta(days=1)
    #     # )

    #     # upload to GCP
    #     # blob = self.bucket.blob(file.filename)
    #     # blob.upload_from_file(
    #     #     file.stream,
    #     #     content_type=file.content_type or "application/octet-stream",
    #     #     rewind=True,
    #     # )

    #     # # More fields attached
    #     # data["url"] = blob.media_link
    #     self.logger.warning(data)

    #     # # uncomment this line
    #     # # blob.make_public() # Permissions are really messed up idk -- error : google.api_core.exceptions.BadRequest: 400 GET https://storage.googleapis.com/storage/v1/b/partyscene/o/file/acl?prettyPrint=false: Cannot get legacy ACL for an object when uniform bucket-level access is enabled. Read more at https://cloud.google.com/storage/docs/uniform-bucket-level-acces
    #     result = await self.__media_handler.create_media_metadata(data)
    #     return jsonify(result), HTTPStatus.CREATED

    @route("/media/sign", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def sign(self):
        """Sign a media in the Bucket for access"""
        filename = request.args.get("filename")

        if not filename:
            return "Filename missing", HTTPStatus.BAD_REQUEST

        # media_url = await obs.sign_async(
        #     self.OBS_STORE, "GET", filename, timedelta(days=1)
        # )

        media_url = await self.generate_download_signed_url_v4(filename)

        return media_url, HTTPStatus.OK

    
    async def generate_download_signed_url_v4(self, blob_name):
        """Generates a v4 signed URL for downloading a blob.

        Note that this method requires a service account key file. You can not use
        this if you are using Application Default Credentials from Google Compute
        Engine or from the Google Cloud SDK.
        """
        blob = self.bucket.blob(blob_name)

        url = blob.generate_signed_url(
            version="v4",
            # This URL is valid for 15 minutes
            expiration=timedelta(days=1),
            # Allow GET requests using this URL.
            method="GET",
        )
        return url
