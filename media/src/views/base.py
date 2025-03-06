from quart import current_app as app, request, jsonify
from quart.datastructures import FileStorage
from quart_jwt_extended import jwt_required, get_jwt_identity
from google.cloud import storage
import werkzeug.datastructures

from classful import route, QuartClassful
from ..connectors import MediaDB
from http import HTTPStatus

import os
import io
import werkzeug
from datetime import datetime

class BaseView(QuartClassful):

    def __init__(self):
        self.GCP_client = storage.Client(os.getenv("GOOGLE_CLOUD_PROJECT"))
        self.bucket = self.GCP_client.bucket("partyscene")
        self.__media_handler: MediaDB = app.conn

    @route("/health", methods=["GET"])
    async def healthcheck(self):
        """
        Simple health check endpoint that verifies service and dependency status.
        Returns 200 OK if everything is healthy, 503 Service Unavailable otherwise.
        """
        health_status = {
            "service": "auth",
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "dependencies": {
                "database": "unknown",
                "redis": "unknown"
            }
        }
        
        # Check database connection
        try:
            db_info = await self.__media_handler.db.info()
            health_status["dependencies"]["database"] = "healthy"
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            health_status["dependencies"]["database"] = "unhealthy"
            health_status["status"] = "degraded"
        
        # Check Redis connection
        try:
            redis_ping = await self.redis.ping()
            health_status["dependencies"]["redis"] = "healthy" if redis_ping else "unhealthy"
            if not redis_ping:
                health_status["status"] = "degraded"
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            health_status["dependencies"]["redis"] = "unhealthy"
            health_status["status"] = "degraded"
        
        status_code = HTTPStatus.OK if health_status["status"] == "healthy" else HTTPStatus.SERVICE_UNAVAILABLE
        
        return jsonify(health_status), status_code

    @route("/upload", methods=["GET", "POST"])
    @jwt_required
    async def upload(self):
        """Upload a media type to our GCP Bucket"""
        ...
        file: werkzeug.datastructures.FileStorage = (await request.files).get("file")

        # Get the data and attach fields
        data = await request.form
        data = data.to_dict()
        data["creator"] = get_jwt_identity()

        # upload to GCP
        blob = self.bucket.blob(file.filename)
        blob.upload_from_file(
            file.stream,
            content_type=file.content_type or "application/octet-stream",
            rewind=True,
        )

        # More fields attached
        data["url"] = blob.media_link

        # uncomment this line
        # blob.make_public() # Permissions are really messed up idk -- error : google.api_core.exceptions.BadRequest: 400 GET https://storage.googleapis.com/storage/v1/b/partyscene/o/file/acl?prettyPrint=false: Cannot get legacy ACL for an object when uniform bucket-level access is enabled. Read more at https://cloud.google.com/storage/docs/uniform-bucket-level-acces
        result = await self.__media_handler.create_media_metadata(data)
        return jsonify(result), HTTPStatus.CREATED
