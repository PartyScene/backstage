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

    async def _check_attendee_status(self, event_id: str, user_id: str) -> bool:
        """
        Check if user is an attendee of the event.
        Only attendees can create/manage streams for an event.
        """
        try:
            async with self.conn.pool.acquire() as conn:
                # Check if user is attending the event
                result = await conn.query(
                    """
                    SELECT VALUE id FROM attends 
                    WHERE in = type::thing("users", $user_id) 
                    AND out = type::thing("events", $event_id)
                    """,
                    {"event_id": event_id, "user_id": user_id},
                )
                
                if result and len(result) > 0:
                    app.logger.info(f"User {user_id} is attending event {event_id}")
                    return True
                
                app.logger.warning(
                    f"Permission denied: user {user_id} is not attending event {event_id}"
                )
                return False
                
        except Exception as e:
            app.logger.error(f"Attendee check failed for user {user_id} on event {event_id}: {e}")
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
        Get all livestream information for an event.
        Returns a list of all active streams with user information.
        """
        # Validate event_id
        if not self._validate_event_id(event_id):
            return jsonify({"error": "Invalid event ID format"}), HTTPStatus.BAD_REQUEST

        # Check Redis cache first
        cache_key = f"livestream:all:{event_id}"
        cache_ttl = 10  # 10 seconds cache for stream info

        try:
            cached_data = await self.redis.get(cache_key)
            if cached_data:
                app.logger.info(f"Cache HIT for all streams {event_id}")
                import orjson
                return jsonify(orjson.loads(cached_data)), HTTPStatus.OK

            app.logger.info(f"Cache MISS for all streams {event_id}")
        except redis.exceptions.RedisError as e:
            app.logger.error(f"Redis GET error: {e}. Proceeding without cache.")

        # Fetch all streams from database
        try:
            streams = await self.conn.fetch_cloudflare_scene(event_id)

            if not streams:
                return jsonify({"streams": [], "count": 0}), HTTPStatus.OK

            # Normalize to list
            streams_list = streams if isinstance(streams, list) else [streams]
            
            # Enrich each stream with fresh playback info from Cloudflare
            await self._ensure_scenes_client_initialized()
            enriched_streams = []
            
            for stream in streams_list:
                input_uid = stream.get("input_uid")
                if input_uid:
                    try:
                        # Fetch live video data from Cloudflare API: GET /live_inputs/{uid}/videos
                        video_data = await self.scenes_client._retrieve_video(input_uid, live_only=True)
                        if video_data and "playback" in video_data:
                            # Add fresh playback URLs to stream
                            stream["playback"] = video_data["playback"]
                            stream["status"] = video_data.get("status", {})
                            
                            # Update database with fresh playback data
                            try:
                                scene_id = stream.get("id", "").split(":")[-1]  # Extract ID from "scenes:abc123"
                                await self.conn.update_cloudflare_scene_playback(
                                    scene_id,
                                    video_data["playback"]
                                )
                            except Exception as db_err:
                                app.logger.warning(f"Failed to update playback for stream {input_uid}: {db_err}")
                    except Exception as cf_err:
                        app.logger.warning(f"Failed to fetch playback for stream {input_uid}: {cf_err}")
                
                enriched_streams.append(stream)

            # Format response with enriched user info and playback
            response_data = {
                "event_id": event_id,
                "streams": enriched_streams,
                "count": len(enriched_streams),
            }

            # Cache the result
            try:
                import orjson
                await self.redis.set(cache_key, orjson.dumps(response_data), ex=cache_ttl)
                app.logger.info(f"Cached {response_data['count']} streams for event {event_id}")
            except redis.exceptions.RedisError as e:
                app.logger.error(f"Redis SET error: {e}. Serving without caching.")

            return jsonify(response_data), HTTPStatus.OK

        except Exception as e:
            app.logger.exception(f"Unexpected error getting streams for event {event_id}")
            return (
                jsonify({"error": "Failed to retrieve livestreams"}),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @route("/scenes/<event_id>", methods=["DELETE"])
    @jwt_required
    async def end_livestream(self, event_id):
        """
        End and delete user's own livestream for an event.
        Users can only delete their own streams.
        """
        # Validate event_id
        if not self._validate_event_id(event_id):
            return jsonify({"error": "Invalid event ID format"}), HTTPStatus.BAD_REQUEST

        user_id = get_jwt_identity()

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
            # Check if user's stream exists
            user_stream = await self.conn.fetch_cloudflare_scene(event_id, user_id)
            if not user_stream:
                return (
                    jsonify({"error": "You don't have an active stream for this event"}),
                    HTTPStatus.NOT_FOUND,
                )

            # Delete from Cloudflare
            stream_deleted = await self.scenes_client.delete_stream(event_id, user_id)
            
            # Delete from database
            db_deleted = await self.conn.delete_cloudflare_scene(event_id, user_id)
            
            if stream_deleted or db_deleted:
                # Invalidate cache
                try:
                    await self.redis.delete(f"livestream:all:{event_id}")
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
            app.logger.error(f"Cloudflare API error deleting stream for user {user_id}, event {event_id}: {e}")
            return (
                jsonify({"error": "Streaming provider error", "detail": str(e)}),
                HTTPStatus.BAD_GATEWAY,
            )
        except Exception as e:
            app.logger.exception(f"Unexpected error deleting stream for user {user_id}, event {event_id}")
            return (
                jsonify({"error": "Failed to delete livestream"}),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @route("/scenes/<event_id>/report", methods=["POST"])
    @jwt_required
    async def report_livestream(self, event_id):
        """
        Report a livestream for violations or inappropriate content.
        Any authenticated user can report a stream.
        """
        # Validate event_id
        if not self._validate_event_id(event_id):
            return jsonify({"error": "Invalid event ID format"}), HTTPStatus.BAD_REQUEST

        reporter = get_jwt_identity()
        data = await request.get_json()
        reason = data.get("reason", "")
        
        if not reason:
            status_code = HTTPStatus.BAD_REQUEST
            return (
                jsonify(message="Reason is required", status=status_code.phrase),
                status_code,
            )

        # Check if the livestream/scene exists
        try:
            scene_info = await self.conn.fetch_cloudflare_scene(event_id)
            if not scene_info:
                status_code = HTTPStatus.NOT_FOUND
                return (
                    jsonify(message="Livestream not found", status=status_code.phrase),
                    status_code,
                )

            # Create report
            if result := await self.conn._report_resource(
                {"reason": reason, "reporter": reporter, "resource": scene_info["id"]}
            ):
                status_code = HTTPStatus.CREATED
                return (
                    jsonify(
                        message="Livestream reported successfully",
                        data=result,
                        status=status_code.phrase,
                    ),
                    status_code,
                )
            
            # If _report_resource returned falsy value
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(message="Failed to create report", status=status_code.phrase),
                status_code,
            )
            
        except Exception as e:
            app.logger.exception(f"Error reporting livestream {event_id}")
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to report livestream: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
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

        # Check if user is attending the event
        user_id = get_jwt_identity()
        if not await self._check_attendee_status(event_id, user_id):
            return (
                jsonify({"error": "Unauthorized - only event attendees can create streams"}),
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
            # Check if user already has a stream for this event (idempotency)
            existing_stream = await self.conn.fetch_cloudflare_scene(event_id, user_id)
            if existing_stream:
                app.logger.info(f"User {user_id} already has a stream for event {event_id}")
                return jsonify(existing_stream), HTTPStatus.OK

            # Create new stream on Cloudflare
            stream_create_resp = await self.scenes_client.create_stream(event_id, user_id)
            if stream_create_resp:
                # Store stream in database with user association
                stream_info = await self.conn.store_cloudflare_scene(
                    stream_create_resp, event_id, user_id
                )
                
                # Invalidate cache
                try:
                    await self.redis.delete(f"livestream:all:{event_id}")
                except redis.exceptions.RedisError as e:
                    app.logger.error(f"Redis cache invalidation error: {e}")
                
                app.logger.info(f"Successfully created stream for user {user_id} on event {event_id}")
                return jsonify(stream_info), HTTPStatus.CREATED
            else:
                app.logger.error(f"Stream creation returned false for user {user_id}, event {event_id}")
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

