from pprint import pprint
from quart import (
    make_response,
    render_template,
    current_app as app,
    request,
    jsonify,
    logging,
)
from quart.datastructures import FileStorage

from quart_jwt_extended import jwt_required
from http import HTTPStatus
from shared.classful import route, QuartClassful
from shared.workers import cloudflare_stream
from datetime import datetime
from aiocache import cached
from livestream.src.connectors import LiveStreamDB


class BaseView(QuartClassful):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.redis = app.redis  # type: ignore
        self.conn: LiveStreamDB = app.conn
        self.scenes_client = cloudflare_stream.create_livestream_client(app, app.logger)

    @route("/", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def index(self):
        return await self.healthcheck()

    @route("/health", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def healthcheck(self):
        """
        Simple health check endpoint that verifies service and dependency status.
        Returns 200 OK if everything is healthy, 503 Service Unavailable otherwise.
        """
        health_status = {
            "service": "microservices.livestream",
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "dependencies": {"database": "unknown", "redis": "unknown"},
        }

        # Check database connection
        try:
            db_info = await self.conn._info()
            health_status["dependencies"]["database"] = "healthy"
        except Exception as e:
            app.logger.error(f"Database health check failed: {e}")
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
            app.logger.error(f"Redis health check failed: {e}")
            health_status["dependencies"]["redis"] = "unhealthy"
            health_status["status"] = "degraded"

        status_code = (
            HTTPStatus.OK
            if health_status["status"] == "healthy"
            else HTTPStatus.SERVICE_UNAVAILABLE
        )

        return jsonify(health_status), status_code

    @route("/scenes/<event_id>", methods=["GET"])
    @jwt_required
    async def get_livestream(self, event_id):
        try:
            vod = request.args.get("vod", False)
            if vod:
                stream_info = await self.scenes_client.get_vods(event_id)
            else:
                stream_info = await self.scenes_client.get_live(event_id)

            return jsonify(stream_info), HTTPStatus.OK
        except:
            return (
                jsonify({"error": "Failed to get livestream"}),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @route("/scenes/<event_id>", methods=["DELETE"])
    async def end_livestream(self, event_id):
        try:
            stream_deleted = await self.scenes_client.delete_stream(event_id)
            if stream_deleted:
                return "", HTTPStatus.NO_CONTENT
            return "", HTTPStatus.NOT_FOUND
        except:
            return (
                jsonify({"error": "Failed to get livestream"}),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @route("/scenes/<event_id>", methods=["POST"])
    async def create_livestream(self, event_id):  # Renamed from index to manage_stream
        """
        Create a livestream for a given event using the GCP or Cloudflare Livestream API.

        This method follows a comprehensive livestream creation workflow (for GCP):
        1. Create a Stream: Initializes a new livestream for the specified event
        2. Create Input: Sets up the input configuration for the livestream
        3. Record Input: Prepares the livestream to start recording
        4. Store Output: Saves the livestream configuration and metadata
        5. Connect to Output: Establishes the output streaming destination

        And for cloudflare, this method follows a comprehensive livestream creation workflow:
        1. Create a Stream Input: Initializes a new livestream for the specified event
        2. Store Stream Input for Creators: Stores the stream input for streaming by creators
        3. Retrieve VODs: Retrieves the VODs for the specified input [live/vod]
        4. Delete Input: Deletes the stream input

        Args:
            event_id (str): Unique identifier for the event to create a livestream for

        Returns:
            tuple: A JSON response containing stream information and HTTP status code
                - On success: (stream_info, HTTPStatus.CREATED)
                - On failure: (error_message, HTTPStatus.INTERNAL_SERVER_ERROR)

        Raises:
            Exception: If any step in the livestream creation process fails
        """
        # try:
        #     stream_create_resp = await self.livestream.start_stream(event_id)
        #     if stream_create_resp:
        #         stream_info = await self.livestream.get_stream(event_id)
        #         return jsonify(stream_info), HTTPStatus.CREATED
        # except:
        #     return (
        #         jsonify({"error": "Failed to create livestream"}),
        #         HTTPStatus.INTERNAL_SERVER_ERROR,
        #     )

        try:
            stream_create_resp = await self.scenes_client.create_stream(event_id)
            if stream_create_resp:
                stream_info = await self.scenes_client.fetch_stream(event_id)
                return jsonify(stream_info), HTTPStatus.CREATED
        except:
            return (
                jsonify({"error": "Failed to create livestream"}),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
