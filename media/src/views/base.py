from quart import current_app as app, request, jsonify, logging, Response
from quart.datastructures import FileStorage
from quart_jwt_extended import jwt_required, get_jwt_identity
from google.cloud import storage
import google.auth
from datetime import timedelta
import werkzeug.datastructures

from shared.classful import route, QuartClassful
from media.src.connectors import MediaDB
from http import HTTPStatus

import os
import io
import werkzeug
from datetime import datetime, timedelta
import redis.exceptions
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
        message = "Service is healthy"
        status_code = HTTPStatus.OK

        # Check database connection
        try:
            db_info = await self.__media_handler._info()
            health_status["dependencies"]["database"] = "healthy"
        except Exception as e:
            self.logger.error(f"Database health check failed: {e}")
            health_status["dependencies"]["database"] = "unhealthy"
            health_status["status"] = "degraded"
            message = "Service degraded: Database connection failed"
            status_code = HTTPStatus.SERVICE_UNAVAILABLE

        # Check Redis connection
        try:
            redis_ping = await self.redis.ping()
            health_status["dependencies"]["redis"] = (
                "healthy" if redis_ping else "unhealthy"
            )
            if not redis_ping:
                health_status["status"] = "degraded"
                message = "Service degraded: Redis connection failed"
                status_code = HTTPStatus.SERVICE_UNAVAILABLE
        except Exception as e:
            self.logger.error(f"Redis health check failed: {e}")
            health_status["dependencies"]["redis"] = "unhealthy"
            health_status["status"] = "degraded"
            message = "Service degraded: Redis connection failed"
            status_code = HTTPStatus.SERVICE_UNAVAILABLE

        return (
            jsonify(data=health_status, message=message, status=status_code.phrase),
            status_code,
        )

    @route("/media/sign", methods=["GET"])
    # @cached(ttl=60 * 60 * 72) # Caching handled manually with Redis below
    async def sign(self):
        """Sign a media in the Bucket for access"""
        filename = request.args.get("filename")

        if not filename:
            status_code = HTTPStatus.BAD_REQUEST
            return (
                jsonify(message="Filename missing", status=status_code.phrase),
                status_code,
            )

        # Define a specific cache key prefix for this endpoint
        cache_key = f"media:signed_url:{filename}"
        # Define TTL for the cache (e.g., 1 hour = 3600 seconds)
        # Should be less than the signed URL validity (1 day)
        cache_ttl = 3600 * 22

        cached_url = None
        try:
            # 1. Check Redis cache first
            cached_url = await self.redis.get(cache_key)
            if cached_url:
                self.logger.info(f"Cache HIT for signed URL: {filename}")
                # Return cached URL
                status_code = HTTPStatus.OK
                return cached_url, status_code
                # return (
                #     jsonify(
                #         data={"signed_url": cached_url},
                #         message="Signed URL retrieved from cache.",
                #         status=status_code.phrase,
                #     ),
                #     status_code,
                # )

            self.logger.info(f"Cache MISS for signed URL: {filename}")

        except redis.exceptions.RedisError as e:
            self.logger.error(
                f"Redis GET error for key {cache_key}: {e}. Proceeding without cache."
            )
            # Fallback: If Redis GET fails, generate a new URL without caching

        # --- Cache MISS or Redis GET Error ---
        self.logger.warning(f"Generating new signed URL for Filename: {filename}")

        try:
            # 2. Generate the signed URL (original logic)
            media_url = await obs.sign_async(
                self.OBS_STORE, "GET", filename, timedelta(days=1)
            )
            # Alternative method call if needed:
            # media_url = await self.generate_download_signed_url_v4(filename)

        except Exception as e:
            # Handle potential errors during URL signing
            self.logger.error(
                f"Error generating signed URL for {filename}: {e}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to generate signed URL for {filename}",
                    status=status_code.phrase,
                ),
                status_code,
            )

        # 3. Store the newly generated URL in Redis (if cache wasn't hit and GET didn't fail)
        if (
            cached_url is None
        ):  # Only store if it was a definite miss (and GET didn't error)
            try:
                await self.redis.set(cache_key, media_url, ex=cache_ttl)
                self.logger.info(
                    f"Stored signed URL in cache for {filename} with TTL {cache_ttl}s"
                )
            except redis.exceptions.RedisError as e:
                self.logger.error(
                    f"Redis SET error for key {cache_key}: {e}. Serving URL without caching."
                )
                # If SET fails, we still return the generated URL, just don't cache it

        # Return the newly generated URL
        status_code = HTTPStatus.OK
        return media_url, status_code
        # return (
        #     jsonify(
        #         data={"signed_url": media_url},
        #         message="Signed URL generated successfully.",
        #         status=status_code.phrase,
        #     ),
        #     status_code,
        # )

    async def generate_download_signed_url_v4(self, blob_name):
        """Generates a v4 signed URL for downloading a blob.

        Note that this method requires a service account key file. You can not use
        this if you are using Application Default Credentials from Google Compute
        Engine or from the Google Cloud SDK.
        """
        blob = self.bucket.blob(blob_name)
        creds = await self.get_impersonated_credentials()

        url = blob.generate_signed_url(
            service_account_email=creds.service_account_email,
            access_token=creds.token,
            version="v4",
            # This URL is valid for 15 minutes
            expiration=timedelta(days=1),
            # Allow GET requests using this URL.
            method="GET",
        )
        return url

    async def get_impersonated_credentials(self):
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]

        credentials, project = google.auth.default(scopes=None)

        if credentials.token is None:
            credentials.refresh(google.auth.transport.requests.Request())

        self.logger.warning(credentials.service_account_email)
        return credentials

        # Impersonated credentials logic might be complex/unnecessary depending on setup
        # signing_credentials = google.auth.impersonated_credentials.Credentials(
        #     source_credentials=credentials,
        #     target_principal=credentials.service_account_email,
        #     target_scopes=scopes,
        #     lifetime=datetime.timedelta(seconds=3600),
        #     delegates=[credentials.service_account_email],
        # )
        # return signing_credentials
