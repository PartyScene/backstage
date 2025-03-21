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
from ..lib import create_livestream_client

from quart_jwt
from http import HTTPStatus
from shared.classful import route, QuartClassful
from datetime import datetime
from aiocache import cached


class BaseView(QuartClassful):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.create_logger(app)
        self.redis = app.redis
        self.livestream = create_livestream_client(app.conn, self.logger)

    @route("/", methods=["GET"])
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
            db_info = await self.livestream.db.db.info()
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

    @route("/scenes/<event_id>", methods=["GET"])
    @jwt_required
    async def get_livestream(self, event_id):
        try:
            stream_info = await self.livestream.get_stream(event_id)
            if not isinstance(stream_info, dict):
                return jsonify(stream_info), HTTPStatus.NOT_FOUND
            return jsonify(stream_info), HTTPStatus.OK
        except:
            return (
                jsonify({"error": "Failed to get livestream"}),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @route("/scenes/<event_id>", methods=["DELETE"])
    async def end_livestream(self, event_id):
        try:
            stream_info = await self.livestream.end_stream(event_id)
            if not isinstance(stream_info, dict):
                return jsonify(stream_info), HTTPStatus.NOT_FOUND
            return jsonify(stream_info), HTTPStatus.NO_CONTENT
        except:
            return (
                jsonify({"error": "Failed to get livestream"}),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @route("/scenes/<event_id>", methods=["POST"])
    async def create_livestream(self, event_id):  # Renamed from index to manage_stream
        """
        Flow: Create a Stream -> Create Input -> Record Input -> Store Output -> Connect to Output
        API Endpoint to create a livestream input using GCP Livestream API.
        """

        try:
            stream_create_resp = await self.livestream.start_stream(event_id)
            if stream_create_resp:
                stream_info = await self.livestream.get_stream(event_id)
                return jsonify(stream_info), HTTPStatus.CREATED
        except:
            return (
                jsonify({"error": "Failed to create livestream"}),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
