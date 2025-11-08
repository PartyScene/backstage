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

from quart_jwt_extended import jwt_required, get_jwt_identity
import jwt, os
from http import HTTPStatus
from shared.classful import route, QuartClassful
from shared.workers import cloudflare_stream
from datetime import datetime, timedelta
import shared.utils
from aiocache import cached
from livestream.src.connectors import LiveStreamDB
from cloudflare._exceptions import APIError, APIConnectionError, APITimeoutError
from surrealdb import RecordID

import redis.exceptions
import re


VIDEOSDK_API_KEY = os.environ.get("VIDEOSDK_API_KEY", "")
VIDEOSDK_SECRET_KEY = os.environ.get("VIDEOSDK_SECRET_KEY", "")
TOKEN_EXPIRATION_IN_SECONDS = os.environ.get("TOKEN_EXPIRATION_IN_SECONDS", "")


class BaseView(QuartClassful):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.redis = app.redis  # type: ignore
        self.conn: LiveStreamDB = app.conn
        self.scenes_client = cloudflare_stream.create_livestream_client(app, app.logger)
        self._scenes_client_initialized = False

    async def _ensure_scenes_client_initialized(self):
        """Lazy initialization of scenes client"""
        if not self._scenes_client_initialized:
            try:
                await self.scenes_client.initialize()
                self._scenes_client_initialized = True
            except Exception as e:
                app.logger.error(f"Failed to initialize Cloudflare client: {e}")
                raise

    def _validate_event_id(self, event_id: str) -> bool:
        """Validate event_id format"""
        if not event_id or len(event_id) > 100:
            return False
        # Basic alphanumeric check (adjust pattern as needed)
        if not re.match(r'^[a-zA-Z0-9_-]+$', event_id):
            return False
        return True

    async def _check_event_permission(self, event_id: str, user_id: str) -> bool:
        """
        Check if user has permission to manage livestream for this event.
        Only the event creator can create/delete streams.
        """
        try:
            async with self.conn.pool.acquire() as conn:
                event = await conn.select(RecordID("events", event_id))
                
                if not event:
                    app.logger.warning(f"Event {event_id} not found during permission check")
                    return False
                
                creator_id = event.get("creator")
                if creator_id == RecordID("users", user_id):
                    return True
                
                app.logger.warning(
                    f"Permission denied: user {user_id} is not creator of event {event_id} (creator: {creator_id})"
                )
                return False
                
        except Exception as e:
            app.logger.error(f"Permission check failed for user {user_id} on event {event_id}: {e}")
            return False

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
            "service": "microservices.scenes",
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
        """
        Get livestream information for an event.
        Supports both live streams and VOD recordings.
        
        Query params:
            vod (bool): If true, retrieve VOD recording instead of live stream
        """
        # Validate event_id
        if not self._validate_event_id(event_id):
            return jsonify({"error": "Invalid event ID format"}), HTTPStatus.BAD_REQUEST

        # Ensure client is initialized
        try:
            await self._ensure_scenes_client_initialized()
        except Exception as e:
            app.logger.error(f"Client initialization failed: {e}")
            return (
                jsonify({"error": "Streaming service unavailable"}),
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        # Check Redis cache first
        vod = request.args.get("vod", "false").lower() == "true"
        cache_type = "vod" if vod else "live"
        cache_key = f"livestream:{cache_type}:{event_id}"
        cache_ttl = 10  # 10 seconds cache for stream info

        try:
            cached_data = await self.redis.get(cache_key)
            if cached_data:
                app.logger.info(f"Cache HIT for stream {event_id}")
                import json
                return jsonify(json.loads(cached_data)), HTTPStatus.OK

            app.logger.info(f"Cache MISS for stream {event_id}")
        except redis.exceptions.RedisError as e:
            app.logger.error(f"Redis GET error: {e}. Proceeding without cache.")

        # Fetch from Cloudflare
        try:
            if vod:
                stream_info = await self.scenes_client.get_vods(event_id)
            else:
                stream_info = await self.scenes_client.get_live(event_id)

            if not stream_info:
                return (
                    jsonify({"error": "Stream not found or not ready yet"}),
                    HTTPStatus.NOT_FOUND,
                )

            # Cache the result
            try:
                import json
                await self.redis.set(cache_key, json.dumps(stream_info), ex=cache_ttl)
                app.logger.info(f"Cached stream info for {event_id}")
            except redis.exceptions.RedisError as e:
                app.logger.error(f"Redis SET error: {e}. Serving without caching.")

            return jsonify(stream_info), HTTPStatus.OK

        except APIError as e:
            app.logger.error(f"Cloudflare API error getting stream {event_id}: {e}")
            return (
                jsonify({"error": "Streaming provider error", "detail": str(e)}),
                HTTPStatus.BAD_GATEWAY,
            )
        except Exception as e:
            app.logger.exception(f"Unexpected error getting stream {event_id}")
            return (
                jsonify({"error": "Failed to retrieve livestream"}),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @route("/scenes/<event_id>", methods=["DELETE"])
    @jwt_required
    async def end_livestream(self, event_id):
        """
        End and delete a livestream for an event.
        Only the event creator can delete the stream.
        """
        # Validate event_id
        if not self._validate_event_id(event_id):
            return jsonify({"error": "Invalid event ID format"}), HTTPStatus.BAD_REQUEST

        # Check permissions
        user_id = get_jwt_identity()
        if not await self._check_event_permission(event_id, user_id):
            return (
                jsonify({"error": "Unauthorized - only event creator can delete stream"}),
                HTTPStatus.FORBIDDEN,
            )

        # Ensure client is initialized
        try:
            await self._ensure_scenes_client_initialized()
        except Exception as e:
            app.logger.error(f"Client initialization failed: {e}")
            return (
                jsonify({"error": "Streaming service unavailable"}),
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:
            stream_deleted = await self.scenes_client.delete_stream(event_id)
            if stream_deleted:
                # Invalidate cache
                try:
                    await self.redis.delete(f"livestream:live:{event_id}")
                    await self.redis.delete(f"livestream:vod:{event_id}")
                    app.logger.info(f"Invalidated cache for event {event_id}")
                except redis.exceptions.RedisError as e:
                    app.logger.error(f"Redis DELETE error: {e}")

                return jsonify({"message": "Stream deleted successfully"}), HTTPStatus.NO_CONTENT
            else:
                return (
                    jsonify({"error": "Stream not found"}),
                    HTTPStatus.NOT_FOUND,
                )

        except APIError as e:
            app.logger.error(f"Cloudflare API error deleting stream {event_id}: {e}")
            return (
                jsonify({"error": "Streaming provider error", "detail": str(e)}),
                HTTPStatus.BAD_GATEWAY,
            )
        except Exception as e:
            app.logger.exception(f"Unexpected error deleting stream {event_id}")
            return (
                jsonify({"error": "Failed to delete livestream"}),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @route("/scenes/<event_id>", methods=["POST"])
    @jwt_required
    async def create_livestream(self, event_id):
        """
        Create a livestream for a given event using Cloudflare Stream.

        Cloudflare livestream creation workflow:
        1. Validate event ID and user permissions
        2. Create a Stream Input: Initializes a new livestream for the specified event
        3. Store Stream Input: Stores the stream credentials in database
        4. Return stream credentials to creator for OBS/streaming software

        Args:
            event_id (str): Unique identifier for the event to create a livestream for

        Returns:
            tuple: A JSON response containing stream information and HTTP status code
                - On success: (stream_info, HTTPStatus.CREATED)
                - On already exists: (stream_info, HTTPStatus.OK)
                - On failure: (error_message, appropriate HTTP status)
        """
        # Validate event_id
        if not self._validate_event_id(event_id):
            return jsonify({"error": "Invalid event ID format"}), HTTPStatus.BAD_REQUEST

        # Check permissions
        user_id = get_jwt_identity()
        if not await self._check_event_permission(event_id, user_id):
            return (
                jsonify({"error": "Unauthorized - only event creator can create stream"}),
                HTTPStatus.FORBIDDEN,
            )

        # Ensure client is initialized
        try:
            await self._ensure_scenes_client_initialized()
        except Exception as e:
            app.logger.error(f"Client initialization failed: {e}")
            return (
                jsonify({"error": "Streaming service unavailable"}),
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        # Validate distance: host must be within 1km of event location
        try:
            data = await request.get_json()
            if data and "coordinates" in data:
                async with self.conn.pool.acquire() as conn:
                    # Fetch event information
                    event_info = await conn.select(RecordID("events", event_id))
                    
                    if event_info and "location" in event_info:
                        event_coordinates = event_info["location"].get("coordinates")
                        host_coordinates = data["coordinates"]
                        host_coordinates = shared.utils.coordinates_to_geometry_point(host_coordinates)
                        
                        if not event_coordinates or not host_coordinates:
                            return (
                                jsonify({"error": "Coordinates are required for both event and livestream"}),
                                HTTPStatus.BAD_REQUEST,
                            )
                        
                        # Calculate distance
                        distance_result = await conn.query(
                            "RETURN geo::distance($host_location, $event_location);",
                            {
                                "host_location": host_coordinates,
                                "event_location": event_coordinates,
                            },
                        )
                        distance_meters = float(distance_result) if distance_result else float('inf')
                        
                        # Enforce 1km radius
                        MAX_DISTANCE_METERS = 1000
                        if distance_meters > MAX_DISTANCE_METERS:
                            return (
                                jsonify({
                                    "error": f"Host location is {distance_meters:.0f}m from event location (maximum: {MAX_DISTANCE_METERS}m). You must be at the event to go live."
                                }),
                                HTTPStatus.FORBIDDEN,
                            )
                        
                        app.logger.info(f"Distance check passed: {distance_meters:.0f}m from event")
                    else:
                        app.logger.warning(f"Event {event_id} has no location data, skipping distance check")
        except Exception as e:
            app.logger.error(f"Distance validation error for event {event_id}: {e}")
            # Don't block stream creation if distance check fails - log and continue
            # In production, you might want to fail here depending on requirements

        try:
            # Check if stream already exists (idempotency)
            existing_stream = await self.scenes_client.fetch_stream(event_id)
            if existing_stream:
                app.logger.info(f"Stream already exists for event {event_id}")
                return jsonify(existing_stream), HTTPStatus.OK

            # Create new stream
            stream_create_resp = await self.scenes_client.create_stream(event_id)
            if stream_create_resp:
                stream_info = await self.scenes_client.fetch_stream(event_id)
                app.logger.info(f"Successfully created stream for event {event_id}")
                return jsonify(stream_info), HTTPStatus.CREATED
            else:
                app.logger.error(f"Stream creation returned false for event {event_id}")
                return (
                    jsonify({"error": "Stream creation failed"}),
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        except APIConnectionError as e:
            app.logger.error(f"Cloudflare connection error for event {event_id}: {e}")
            return (
                jsonify({"error": "Cannot connect to streaming provider", "detail": str(e)}),
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        except APITimeoutError as e:
            app.logger.error(f"Cloudflare timeout error for event {event_id}: {e}")
            return (
                jsonify({"error": "Streaming provider timeout", "detail": str(e)}),
                HTTPStatus.GATEWAY_TIMEOUT,
            )
        except APIError as e:
            app.logger.error(f"Cloudflare API error for event {event_id}: {e}")
            return (
                jsonify({"error": "Streaming provider error", "detail": str(e)}),
                HTTPStatus.BAD_GATEWAY,
            )
        except RuntimeError as e:
            app.logger.error(f"Runtime error creating stream for event {event_id}: {e}")
            return (
                jsonify({"error": "Service initialization error", "detail": str(e)}),
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            app.logger.exception(f"Unexpected error creating stream for event {event_id}")
            return (
                jsonify({"error": "Failed to create livestream"}),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    # =========================================================================
    # ALTERNATIVE IMPLEMENTATIONS (Not currently used)
    # =========================================================================

    # -------------------------------------------------------------------------
    # VideoSDK Live Implementation
    # -------------------------------------------------------------------------

    @route("/scenes/get-token/<string:event_id>", methods=["POST"])
    @jwt_required
    async def generate_scene_token(self, event_id):
        """
        Generate VideoSDK token for live streaming.
        NOTE: This is an alternative implementation, not currently used.
        """
        expiration = datetime.now() + timedelta(seconds=TOKEN_EXPIRATION_IN_SECONDS)
        payload = {
            "exp": expiration,
            "apikey": VIDEOSDK_API_KEY,
            "permissions": ["allow_join", "allow_mod"],
        }

        if event_id:
            payload["version"] = 2
            payload["roles"] = ["rtc"]
            payload["roomId"] = event_id

        token = jwt.encode(payload, VIDEOSDK_SECRET_KEY, algorithm="HS256")

        return jsonify(
            token=token,
            message="Token generated successfully",
            status=HTTPStatus.OK.phrase,
        )

