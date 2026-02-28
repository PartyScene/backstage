"""
Livestream views — migrated from Cloudflare Stream → GetStream.io (Video + Chat)

Package requirements (add to your requirements.txt / pyproject.toml):
    getstream>=1.0.0          # Video calls + unified token generation (sync SDK)
    stream-chat>=4.0.0        # Chat channels (async SDK)

Environment variables required:
    STREAM_API_KEY            # GetStream app key
    STREAM_API_SECRET         # GetStream app secret

Key architectural changes vs Cloudflare:
  - No more storing RTMP credentials in SurrealDB — Stream manages all of that.
    We only store {event_id -> call_id} so we can look up a call from your event.
  - A `livestream` call is created in backstage mode by default. The host must
    explicitly call POST /scenes/<event_id>/go-live to start broadcasting.
  - A Stream Chat channel (type `livestream`) is created at the same time so
    viewers can chat during the stream. The channel id matches the call id.
  - `getstream` SDK is synchronous (httpx under the hood) so all calls are
    wrapped with asyncio.to_thread to stay non-blocking inside Quart.
  - Token endpoint (GET /scenes/<event_id>/token) replaces the old VideoSDK
    token endpoint — both Video AND Chat share the same Stream user token.
"""

import asyncio
import os
import re
import redis.exceptions

from datetime import datetime, timedelta, UTC
from http import HTTPStatus

from quart import current_app as app, request
from quart_jwt_extended import jwt_required, get_jwt_identity
from aiocache import cached
from surrealdb import RecordID

# GetStream unified SDK (Video + token generation) — sync
from getstream import Stream
from getstream.models import (
    CallRequest,
    MemberRequest,
    UserRequest,
)

# GetStream Chat async SDK
from stream_chat import StreamChatAsync

from shared.classful import route, QuartClassful
from shared.utils import api_response, api_error, coordinates_to_geometry_point
from livestream.src.connectors import LiveStreamDB


# ---------------------------------------------------------------------------
# Stream client setup
# ---------------------------------------------------------------------------

STREAM_API_KEY = os.environ["STREAM_API_KEY"]
STREAM_API_SECRET = os.environ["STREAM_API_SECRET"]

# Sync Video client — safe to create at module level (no event loop needed)
_stream_video_client = Stream(
    api_key=STREAM_API_KEY,
    api_secret=STREAM_API_SECRET,
    timeout=10.0,
)

# Async Chat client — StreamChatAsync creates an aiohttp.TCPConnector on __init__
# which requires a running event loop. We defer creation until first request.
_stream_chat_client: StreamChatAsync | None = None


def _get_chat_client() -> StreamChatAsync:
    """
    Return the StreamChatAsync singleton, creating it on first call.
    Must only be called from within an async context (i.e. inside a request
    handler) where granian/Quart's event loop is already running.
    """
    global _stream_chat_client
    if _stream_chat_client is None:
        _stream_chat_client = StreamChatAsync(
            api_key=STREAM_API_KEY,
            api_secret=STREAM_API_SECRET,
        )
    return _stream_chat_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _run_sync(fn, *args, **kwargs):
    """Run a synchronous Stream SDK call in a thread pool so Quart stays async."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def _call_id_for_event(event_id: str) -> str:
    """
    Deterministic Stream call ID derived from your event_id.
    Stream call IDs must be <= 64 chars, alphanumeric + hyphens/underscores.
    """
    return f"partyscene-{event_id}"


# ---------------------------------------------------------------------------
# BaseView
# ---------------------------------------------------------------------------

class BaseView(QuartClassful):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.redis = app.redis  # type: ignore
        self.conn: LiveStreamDB = app.conn

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_event_id(self, event_id: str) -> bool:
        if not event_id or len(event_id) > 100:
            return False
        return bool(re.match(r"^[a-zA-Z0-9_-]+$", event_id))

    # ------------------------------------------------------------------
    # Permission / timing guard (unchanged from Cloudflare version)
    # ------------------------------------------------------------------

    async def _check_stream_permission(
        self, event_id: str, user_id: str
    ) -> tuple[bool, str | None]:
        """
        Returns (permission_granted, error_message).
        User must be host or attendee and the event must start within 1 hour.
        """
        try:
            async with self.conn.pool.acquire() as conn:
                event_info = await conn.query(
                    "SELECT host, time FROM ONLY type::thing('events', $event_id);",
                    {"event_id": event_id},
                )

                if not event_info:
                    return False, "Event not found"

                # Timing check
                if "time" in event_info:
                    event_time = event_info["time"]
                    now = datetime.now(UTC)
                    if event_time > now + timedelta(hours=1):
                        hours_until = (event_time - now).total_seconds() / 3600
                        return False, (
                            f"Cannot stream yet. Event starts in {hours_until:.1f} hours "
                            "(streaming allowed 1 hour before event)."
                        )

                # Host check
                if event_info.get("host") == RecordID("users", user_id):
                    return True, None

                # Attendee check
                result = await conn.query(
                    """
                    SELECT VALUE id FROM attends
                    WHERE in = type::thing("users", $user_id)
                      AND out = type::thing("events", $event_id)
                    """,
                    {"event_id": event_id, "user_id": user_id},
                )
                if result and len(result) > 0:
                    return True, None

                return False, "Unauthorized — only event hosts and attendees can stream"

        except Exception as exc:
            app.logger.error(f"Permission check failed for {user_id}/{event_id}: {exc}")
            return False, "Permission check failed"

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    @route("/", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def index(self):
        return await self.healthcheck()

    @route("/health", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def healthcheck(self):
        health = {
            "service": "microservices.scenes",
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "dependencies": {"database": "unknown", "redis": "unknown"},
        }

        try:
            await self.conn._info()
            health["dependencies"]["database"] = "healthy"
        except Exception as exc:
            app.logger.error(f"DB health check failed: {exc}")
            health["dependencies"]["database"] = "unhealthy"
            health["status"] = "degraded"

        try:
            pong = await self.redis.ping()
            health["dependencies"]["redis"] = "healthy" if pong else "unhealthy"
            if not pong:
                health["status"] = "degraded"
        except Exception as exc:
            app.logger.error(f"Redis health check failed: {exc}")
            health["dependencies"]["redis"] = "unhealthy"
            health["status"] = "degraded"

        status_code = (
            HTTPStatus.OK
            if health["status"] == "healthy"
            else HTTPStatus.SERVICE_UNAVAILABLE
        )
        return api_response("Service health check completed", status_code, data=health)

    # ------------------------------------------------------------------
    # GET /scenes/<event_id>
    # Returns the Stream call + chat channel info for the event.
    # ------------------------------------------------------------------

    @route("/scenes/<event_id>", methods=["GET"])
    @jwt_required
    async def get_livestream(self, event_id: str):
        """
        Fetch the current livestream state for an event.

        Response includes:
          - call_id, call_type, backstage status, participant count
          - Stream user token (so the RN client can join immediately)
          - Chat channel id
        """
        if not self._validate_event_id(event_id):
            return api_error("Invalid event ID format", HTTPStatus.BAD_REQUEST)

        user_id = get_jwt_identity()
        call_id = _call_id_for_event(event_id)
        cache_key = f"livestream:info:{event_id}"

        # --- Redis cache ---
        try:
            cached_bytes = await self.redis.get(cache_key)
            if cached_bytes:
                import orjson
                data = orjson.loads(cached_bytes)
                # Always generate a fresh token — tokens are user-specific and short-lived
                data["token"] = await _run_sync(
                    _stream_video_client.create_token, user_id
                )
                return api_response("Livestream retrieved successfully", HTTPStatus.OK, data=data)
        except redis.exceptions.RedisError as exc:
            app.logger.error(f"Redis GET error: {exc}")

        # --- Fetch call from Stream ---
        try:
            call = _stream_video_client.video.call("livestream", call_id)
            resp = await _run_sync(call.get)
            call_data = resp.data

            response_data = {
                "event_id": event_id,
                "call_id": call_id,
                "call_type": "livestream",
                "backstage": call_data.call.backstage,
                "created_at": call_data.call.created_at.isoformat()
                if call_data.call.created_at
                else None,
                "started_at": call_data.call.session.started_at.isoformat()
                if call_data.call.session and call_data.call.session.started_at
                else None,
                "participant_count": call_data.call.session.participant_count
                if call_data.call.session
                else 0,
                "chat_channel_id": call_id,  # Chat channel shares the same id
                "chat_channel_type": "livestream",
            }

            # Cache the non-sensitive parts (10 second TTL for live data)
            try:
                import orjson
                await self.redis.set(cache_key, orjson.dumps(response_data), ex=10)
            except redis.exceptions.RedisError as exc:
                app.logger.error(f"Redis SET error: {exc}")

            # Attach a fresh user token AFTER caching
            response_data["token"] = await _run_sync(
                _stream_video_client.create_token, user_id
            )

            return api_response(
                "Livestream retrieved successfully", HTTPStatus.OK, data=response_data
            )

        except Exception as exc:
            # Stream returns a 404-style error if the call doesn't exist yet
            if "not found" in str(exc).lower() or "404" in str(exc):
                return api_response(
                    "No active livestream found",
                    HTTPStatus.OK,
                    data={"event_id": event_id, "call_id": call_id, "backstage": True},
                )
            app.logger.exception(f"Error fetching Stream call for event {event_id}")
            return api_error("Failed to retrieve livestream", HTTPStatus.INTERNAL_SERVER_ERROR)

    # ------------------------------------------------------------------
    # POST /scenes/<event_id>
    # Create (or retrieve) a Stream livestream call + linked Chat channel.
    # ------------------------------------------------------------------

    @route("/scenes/<event_id>", methods=["POST"])
    @jwt_required
    async def create_livestream(self, event_id: str):
        """
        Create a livestream for an event.

        Workflow:
          1. Validate event ID + user permissions + event timing
          2. Optionally validate host is within 1 km of event location
          3. Upsert the Stream user (so Stream knows about them)
          4. get_or_create a Stream call of type 'livestream' (starts in backstage)
          5. get_or_create a Stream Chat channel tied to the same call ID
          6. Return Stream user token + call/channel IDs to the RN client

        The React Native client uses the token + call_id to join via
        @stream-io/video-react-native-sdk and stream-chat-react-native.
        """
        if not self._validate_event_id(event_id):
            return api_error("Invalid event ID format", HTTPStatus.BAD_REQUEST)

        user_id = get_jwt_identity()

        # Permission + timing check
        has_permission, error_msg = await self._check_stream_permission(event_id, user_id)
        if not has_permission:
            return api_error(
                error_msg or "Unauthorized to create stream", HTTPStatus.FORBIDDEN
            )

        # Optional distance validation
        try:
            data = await request.get_json()
            if data and "coordinates" in data:
                async with self.conn.pool.acquire() as conn:
                    event_info = await conn.query(
                        "SELECT * OMIT duration FROM ONLY type::thing('events', $event_id);",
                        {"event_id": event_id},
                    )
                    if event_info and "location" in event_info:
                        event_coords = event_info["location"].get("coordinates")
                        host_coords = coordinates_to_geometry_point(data["coordinates"])

                        if not event_coords or not host_coords:
                            return api_error(
                                "Coordinates required for both event and livestream",
                                HTTPStatus.BAD_REQUEST,
                            )

                        distance_result = await conn.query(
                            "RETURN geo::distance($host_location, $event_location);",
                            {
                                "host_location": host_coords,
                                "event_location": event_coords,
                            },
                        )
                        distance_m = float(distance_result) if distance_result else float("inf")

                        if distance_m > 1000:
                            return api_error(
                                f"Host is {distance_m:.0f}m from event (max 1000m). "
                                "You must be at the event to go live.",
                                HTTPStatus.FORBIDDEN,
                            )
                        app.logger.info(f"Distance check passed: {distance_m:.0f}m")
        except Exception as exc:
            app.logger.error(f"Distance check error for event {event_id}: {exc}")
            # Non-fatal — log and continue

        call_id = _call_id_for_event(event_id)

        try:
            # --- 1. Upsert the user in Stream so they can be added as a member ---
            await _run_sync(
                _stream_video_client.upsert_users,
                UserRequest(id=user_id),
            )

            # --- 2. Create (or retrieve) the Stream video call ---
            call = _stream_video_client.video.call("livestream", call_id)
            call_response = await _run_sync(
                call.get_or_create,
                data=CallRequest(
                    created_by_id=user_id,
                    # Host is admin, others are speakers/viewers per Stream RBAC
                    members=[MemberRequest(user_id=user_id, role="host")],
                    custom={"event_id": event_id},
                ),
            )
            call_data = call_response.data

            # --- 3. Create (or retrieve) the Stream Chat channel ---
            channel = _get_chat_client().channel(
                "livestream",
                call_id,
                data={
                    "name": f"Live chat — {event_id}",
                    "event_id": event_id,
                },
            )
            await channel.create(user_id)

            # --- 4. Generate a Stream user token (covers both Video + Chat) ---
            token = await _run_sync(_stream_video_client.create_token, user_id)

            # Invalidate any cached stream info
            try:
                await self.redis.delete(f"livestream:info:{event_id}")
            except redis.exceptions.RedisError as exc:
                app.logger.error(f"Redis DELETE error: {exc}")

            is_new = call_data.created  # True if just created, False if already existed
            app.logger.info(
                f"{'Created' if is_new else 'Retrieved'} Stream call {call_id} "
                f"for user {user_id} / event {event_id}"
            )

            return api_response(
                "Stream created successfully" if is_new else "Stream already exists",
                HTTPStatus.CREATED if is_new else HTTPStatus.OK,
                data={
                    "call_id": call_id,
                    "call_type": "livestream",
                    "chat_channel_id": call_id,
                    "chat_channel_type": "livestream",
                    "token": token,
                    "api_key": STREAM_API_KEY,
                    # The RN client uses these three values to join the call:
                    #   const client = new StreamVideoClient({ apiKey, user: { id }, token })
                    #   const call = client.call("livestream", call_id)
                    #   await call.join()
                    "backstage": True,  # Stream starts in backstage — host must call go-live
                },
            )

        except Exception as exc:
            app.logger.exception(f"Error creating Stream call for event {event_id}")
            return api_error("Failed to create livestream", HTTPStatus.INTERNAL_SERVER_ERROR)

    # ------------------------------------------------------------------
    # POST /scenes/<event_id>/go-live
    # Take the call out of backstage and start broadcasting to viewers.
    # ------------------------------------------------------------------

    @route("/scenes/<event_id>/go-live", methods=["POST"])
    @jwt_required
    async def go_live(self, event_id: str):
        """
        Move a Stream livestream call from backstage → live.

        Only the event host should call this. Viewers who have already joined
        the call as spectators will automatically see content once this fires.
        """
        if not self._validate_event_id(event_id):
            return api_error("Invalid event ID format", HTTPStatus.BAD_REQUEST)

        user_id = get_jwt_identity()
        has_permission, error_msg = await self._check_stream_permission(event_id, user_id)
        if not has_permission:
            return api_error(error_msg or "Unauthorized", HTTPStatus.FORBIDDEN)

        call_id = _call_id_for_event(event_id)
        try:
            call = _stream_video_client.video.call("livestream", call_id)
            await _run_sync(call.go_live)

            # Invalidate cached stream info so viewers get fresh state
            try:
                await self.redis.delete(f"livestream:info:{event_id}")
            except redis.exceptions.RedisError:
                pass

            app.logger.info(f"Stream {call_id} is now live (user {user_id})")
            return api_response("Stream is now live", HTTPStatus.OK)

        except Exception as exc:
            app.logger.exception(f"go_live failed for {call_id}")
            return api_error("Failed to start broadcast", HTTPStatus.INTERNAL_SERVER_ERROR)

    # ------------------------------------------------------------------
    # POST /scenes/<event_id>/end-live
    # Return the call to backstage (stops the broadcast but keeps the call).
    # ------------------------------------------------------------------

    @route("/scenes/<event_id>/end-live", methods=["POST"])
    @jwt_required
    async def end_live(self, event_id: str):
        """
        Stop broadcasting — moves call back to backstage.
        The call itself still exists (host can go live again).
        To fully delete the call use DELETE /scenes/<event_id>.
        """
        if not self._validate_event_id(event_id):
            return api_error("Invalid event ID format", HTTPStatus.BAD_REQUEST)

        user_id = get_jwt_identity()
        has_permission, error_msg = await self._check_stream_permission(event_id, user_id)
        if not has_permission:
            return api_error(error_msg or "Unauthorized", HTTPStatus.FORBIDDEN)

        call_id = _call_id_for_event(event_id)
        try:
            call = _stream_video_client.video.call("livestream", call_id)
            await _run_sync(call.stop_live)

            try:
                await self.redis.delete(f"livestream:info:{event_id}")
            except redis.exceptions.RedisError:
                pass

            app.logger.info(f"Stream {call_id} moved back to backstage (user {user_id})")
            return api_response("Broadcast stopped", HTTPStatus.OK)

        except Exception as exc:
            app.logger.exception(f"end_live failed for {call_id}")
            return api_error("Failed to stop broadcast", HTTPStatus.INTERNAL_SERVER_ERROR)

    # ------------------------------------------------------------------
    # DELETE /scenes/<event_id>
    # End the call entirely and archive/delete the chat channel.
    # ------------------------------------------------------------------

    @route("/scenes/<event_id>", methods=["DELETE"])
    @jwt_required
    async def end_livestream(self, event_id: str):
        """
        Permanently end a stream:
          1. End the Stream video call
          2. Delete (or freeze) the linked chat channel
          3. Bust the Redis cache
        """
        if not self._validate_event_id(event_id):
            return api_error("Invalid event ID format", HTTPStatus.BAD_REQUEST)

        user_id = get_jwt_identity()
        has_permission, error_msg = await self._check_stream_permission(event_id, user_id)
        if not has_permission:
            return api_error(error_msg or "Unauthorized", HTTPStatus.FORBIDDEN)

        call_id = _call_id_for_event(event_id)
        errors = []

        # --- End the video call ---
        try:
            call = _stream_video_client.video.call("livestream", call_id)
            await _run_sync(call.end)
            app.logger.info(f"Ended Stream call {call_id}")
        except Exception as exc:
            app.logger.error(f"Error ending Stream call {call_id}: {exc}")
            errors.append(f"video: {exc}")

        # --- Freeze the chat channel (preserves history, blocks new messages) ---
        try:
            channel = _get_chat_client().channel("livestream", call_id)
            await channel.update({"frozen": True})
            app.logger.info(f"Froze chat channel {call_id}")
        except Exception as exc:
            app.logger.error(f"Error freezing chat channel {call_id}: {exc}")
            errors.append(f"chat: {exc}")

        # --- Bust cache ---
        try:
            await self.redis.delete(f"livestream:info:{event_id}")
        except redis.exceptions.RedisError as exc:
            app.logger.error(f"Redis DELETE error: {exc}")

        if errors:
            return api_error(
                f"Stream ended with errors: {'; '.join(errors)}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return api_response("Stream ended successfully", HTTPStatus.OK)

    # ------------------------------------------------------------------
    # GET /scenes/<event_id>/token
    # Issue (or refresh) a Stream user token for Video + Chat.
    # ------------------------------------------------------------------

    @route("/scenes/<event_id>/token", methods=["GET"])
    @jwt_required
    async def get_stream_token(self, event_id: str):
        """
        Generate a Stream user token valid for both Video and Chat SDKs.

        The React Native app should call this:
          - On app launch / login
          - When the existing token is about to expire

        Response:
          { token, api_key, user_id, call_id, chat_channel_id }
        """
        if not self._validate_event_id(event_id):
            return api_error("Invalid event ID format", HTTPStatus.BAD_REQUEST)

        user_id = get_jwt_identity()
        call_id = _call_id_for_event(event_id)

        try:
            token = await _run_sync(_stream_video_client.create_token, user_id)
            return api_response(
                "Token generated",
                HTTPStatus.OK,
                data={
                    "token": token,
                    "api_key": STREAM_API_KEY,
                    "user_id": user_id,
                    "call_id": call_id,
                    "call_type": "livestream",
                    "chat_channel_id": call_id,
                    "chat_channel_type": "livestream",
                },
            )
        except Exception as exc:
            app.logger.exception(f"Token generation failed for user {user_id}")
            return api_error("Token generation failed", HTTPStatus.INTERNAL_SERVER_ERROR)

    # ------------------------------------------------------------------
    # POST /scenes/<event_id>/report/<scene_id>
    # Report a stream — unchanged from original, still uses your SurrealDB.
    # ------------------------------------------------------------------

    @route("/scenes/<event_id>/report/<scene_id>", methods=["POST"])
    @jwt_required
    async def report_livestream(self, event_id: str, scene_id: str):
        """
        Report a livestream for inappropriate content.

        Body: { "reason": "..." }

        Note: scene_id here refers to a record in your SurrealDB `scenes` table.
        If you no longer write scenes records you can store Stream call_ids instead.
        """
        if not self._validate_event_id(event_id):
            return api_error("Invalid event ID format", HTTPStatus.BAD_REQUEST)

        reporter = get_jwt_identity()
        body = await request.get_json()
        reason = (body or {}).get("reason", "").strip()

        if not reason:
            return api_error("Reason is required", HTTPStatus.BAD_REQUEST)

        try:
            async with self.conn.pool.acquire() as conn:
                scene_info = await conn.query(
                    "SELECT * FROM ONLY type::thing('scenes', $scene_id);",
                    {"scene_id": scene_id},
                )

            if not scene_info:
                return api_error("Livestream not found", HTTPStatus.NOT_FOUND)

            result = await self.conn._report_resource(
                {"reason": reason, "reporter": reporter, "resource": scene_info["id"]}
            )
            if result:
                return api_response(
                    "Livestream reported successfully",
                    HTTPStatus.CREATED,
                    data=result,
                )
            return api_error("Failed to create report", HTTPStatus.INTERNAL_SERVER_ERROR)

        except Exception as exc:
            app.logger.exception(f"Error reporting livestream {event_id}/{scene_id}")
            return api_error(f"Failed to report: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)
        

# from pprint import pprint
# from quart import (
#     make_response,
#     render_template,
#     current_app as app,
#     request,
#     jsonify,
#     logging,
# )
# from quart.datastructures import FileStorage

# from quart_jwt_extended import jwt_required, get_jwt_identity
# import jwt, os
# from http import HTTPStatus
# from shared.classful import route, QuartClassful
# from shared.workers import cloudflare_stream
# from datetime import datetime, timedelta, UTC
# import shared.utils
# from shared.utils import api_response, api_error
# from aiocache import cached
# from livestream.src.connectors import LiveStreamDB
# from cloudflare._exceptions import APIError, APIConnectionError, APITimeoutError
# from surrealdb import RecordID

# import redis.exceptions
# import re


# VIDEOSDK_API_KEY = os.environ.get("VIDEOSDK_API_KEY", "")
# VIDEOSDK_SECRET_KEY = os.environ.get("VIDEOSDK_SECRET_KEY", "")
# TOKEN_EXPIRATION_IN_SECONDS = os.environ.get("TOKEN_EXPIRATION_IN_SECONDS", "")


# class BaseView(QuartClassful):

#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.redis = app.redis  # type: ignore
#         self.conn: LiveStreamDB = app.conn
#         self.scenes_client = cloudflare_stream.create_livestream_client(app, app.logger)
#         self._scenes_client_initialized = False

#     async def _ensure_scenes_client_initialized(self):
#         """Lazy initialization of scenes client"""
#         if not self._scenes_client_initialized:
#             try:
#                 await self.scenes_client.initialize()
#                 self._scenes_client_initialized = True
#             except Exception as e:
#                 app.logger.error(f"Failed to initialize Cloudflare client: {e}")
#                 raise

#     def _validate_event_id(self, event_id: str) -> bool:
#         """Validate event_id format"""
#         if not event_id or len(event_id) > 100:
#             return False
#         # Basic alphanumeric check (adjust pattern as needed)
#         if not re.match(r'^[a-zA-Z0-9_-]+$', event_id):
#             return False
#         return True

#     async def _check_stream_permission(self, event_id: str, user_id: str) -> tuple[bool, str | None]:
#         """
#         Check if user can create/manage streams for an event.
#         Users can stream if they are either:
#         1. The event host
#         2. An attendee of the event
        
#         Also validates event timing - event must start within 1 hour.
        
#         Returns:
#             tuple[bool, str | None]: (permission_granted, error_message)
#         """
#         try:
#             async with self.conn.pool.acquire() as conn:
#                 # Fetch event info to check host and timing
#                 event_info = await conn.query(
#                     "SELECT host, time FROM ONLY type::thing('events', $event_id);",
#                     {"event_id": event_id}
#                 )
                
#                 if not event_info:
#                     return False, "Event not found"
                
#                 # Check event timing: only allow streaming if event starts within 1 hour
#                 if "time" in event_info:
#                     event_time = event_info["time"]
#                     now = datetime.now(UTC)
#                     one_hour_from_now = now + timedelta(hours=1)
                    
#                     # Reject if event starts more than 1 hour in the future
#                     if event_time > one_hour_from_now:
#                         hours_until_event = (event_time - now).total_seconds() / 3600
#                         error_msg = f"Cannot stream yet. Event starts in {hours_until_event:.1f} hours (streaming allowed 1 hour before event)."
#                         app.logger.warning(f"Timing check failed for user {user_id} on event {event_id}: {error_msg}")
#                         return False, error_msg
                
#                 # Check if user is the host
#                 event_host_id = event_info.get("host")
#                 if event_host_id:
#                     # Extract host ID from RecordID format
#                     if event_host_id == RecordID("users", user_id):
#                         app.logger.info(f"User {user_id} is host of event {event_id}")
#                         return True, None
                
#                 # Check if user is attending the event
#                 result = await conn.query(
#                     """
#                     SELECT VALUE id FROM attends 
#                     WHERE in = type::thing("users", $user_id) 
#                     AND out = type::thing("events", $event_id)
#                     """,
#                     {"event_id": event_id, "user_id": user_id},
#                 )
                
#                 if result and len(result) > 0:
#                     app.logger.info(f"User {user_id} is attending event {event_id}")
#                     return True, None
                
#                 app.logger.warning(
#                     f"Permission denied: user {user_id} is neither host nor attendee of event {event_id}"
#                 )
#                 return False, "Unauthorized - only event hosts and attendees can create streams"
                
#         except Exception as e:
#             app.logger.error(f"Permission check failed for user {user_id} on event {event_id}: {e}")
#             return False, "Permission check failed"

#     @route("/", methods=["GET"])
#     @cached(ttl=60 * 60 * 72)
#     async def index(self):
#         return await self.healthcheck()

#     @route("/health", methods=["GET"])
#     @cached(ttl=60 * 60 * 72)
#     async def healthcheck(self):
#         """
#         Simple health check endpoint that verifies service and dependency status.
#         Returns 200 OK if everything is healthy, 503 Service Unavailable otherwise.
#         """
#         health_status = {
#             "service": "microservices.scenes",
#             "status": "healthy",
#             "timestamp": datetime.now().isoformat(),
#             "dependencies": {"database": "unknown", "redis": "unknown"},
#         }

#         # Check database connection
#         try:
#             db_info = await self.conn._info()
#             health_status["dependencies"]["database"] = "healthy"
#         except Exception as e:
#             app.logger.error(f"Database health check failed: {e}")
#             health_status["dependencies"]["database"] = "unhealthy"
#             health_status["status"] = "degraded"

#         # Check Redis connection
#         try:
#             redis_ping = await self.redis.ping()
#             health_status["dependencies"]["redis"] = (
#                 "healthy" if redis_ping else "unhealthy"
#             )
#             if not redis_ping:
#                 health_status["status"] = "degraded"
#         except Exception as e:
#             app.logger.error(f"Redis health check failed: {e}")
#             health_status["dependencies"]["redis"] = "unhealthy"
#             health_status["status"] = "degraded"

#         status_code = (
#             HTTPStatus.OK
#             if health_status["status"] == "healthy"
#             else HTTPStatus.SERVICE_UNAVAILABLE
#         )

#         return api_response(
#             "Service health check completed",
#             status_code,
#             data=health_status
#         )

#     @route("/scenes/<event_id>", methods=["GET"])
#     @jwt_required
#     async def get_livestream(self, event_id):
#         """
#         Get all livestream information for an event.
#         Returns a list of all active streams with user information.
#         """
#         # Validate event_id
#         if not self._validate_event_id(event_id):
#             return api_error("Invalid event ID format", HTTPStatus.BAD_REQUEST)

#         # Check Redis cache first
#         cache_key = f"livestream:all:{event_id}"
#         cache_ttl = 10  # 10 seconds cache for stream info

#         try:
#             cached_data = await self.redis.get(cache_key)
#             if cached_data:
#                 app.logger.info(f"Cache HIT for all streams {event_id}")
#                 import orjson
#                 return api_response(
#                     "Livestreams retrieved successfully",
#                     HTTPStatus.OK,
#                     data=orjson.loads(cached_data)
#                 )

#             app.logger.info(f"Cache MISS for all streams {event_id}")
#         except redis.exceptions.RedisError as e:
#             app.logger.error(f"Redis GET error: {e}. Proceeding without cache.")

#         # Fetch all streams from database
#         try:
#             streams = await self.conn.fetch_cloudflare_scene(event_id)

#             if not streams:
#                 return api_response(
#                     "No active livestreams found",
#                     HTTPStatus.OK,
#                     data={"streams": [], "count": 0}
#                 )

#             # Normalize to list
#             streams_list = streams if isinstance(streams, list) else [streams]
            
#             # Enrich each stream with fresh playback info from Cloudflare
#             await self._ensure_scenes_client_initialized()
#             enriched_streams = []
            
#             for stream in streams_list:
#                 input_uid = stream.get("input_uid")
#                 if input_uid:
#                     try:
#                         # Fetch live video data from Cloudflare API: GET /live_inputs/{uid}/videos
#                         video_data = await self.scenes_client._retrieve_video(input_uid, live_only=True)
#                         if video_data and "playback" in video_data:
#                             # Add fresh playback URLs to stream
#                             stream["playback"] = video_data["playback"]
#                             stream["status"] = video_data.get("status", {})
                            
#                             # Get live viewer count
#                             viewer_count = await self.scenes_client.get_live_viewer_count(input_uid)
#                             stream["live_viewers"] = viewer_count if viewer_count is not None else 0
                            
#                             # Update database with fresh playback data and set live_started_at if not set
#                             try:
#                                 scene_id = stream.get("id", "").split(":")[-1] if ":" in stream.get("id", "") else stream.get("id", "")
#                                 await self.conn.update_cloudflare_scene_playback(
#                                     scene_id,
#                                     video_data["playback"]
#                                 )
                                
#                                 # Set live_started_at timestamp if stream just went live (only if not already set)
#                                 if not stream.get("live_started_at"):
#                                     await self.conn.update_scene_live_start(scene_id)
#                                     app.logger.info(f"Stream {scene_id} went live - started 3-minute timer")
                                
#                             except Exception as db_err:
#                                 app.logger.warning(f"Failed to update playback for stream {input_uid}: {db_err}")
#                         else:
#                             # Stream offline or not ready
#                             stream["live_viewers"] = 0
#                     except Exception as cf_err:
#                         app.logger.warning(f"Failed to fetch playback for stream {input_uid}: {cf_err}")
#                         stream["live_viewers"] = 0
                
#                 enriched_streams.append(stream)

#             # Format response with enriched user info and playback
#             response_data = {
#                 "event_id": event_id,
#                 "streams": enriched_streams,
#                 "count": len(enriched_streams),
#             }

#             # Cache the result
#             try:
#                 import orjson
#                 await self.redis.set(cache_key, orjson.dumps(response_data), ex=cache_ttl)
#                 app.logger.info(f"Cached {response_data['count']} streams for event {event_id}")
#             except redis.exceptions.RedisError as e:
#                 app.logger.error(f"Redis SET error: {e}. Serving without caching.")

#             return api_response(
#                 "Livestreams retrieved successfully",
#                 HTTPStatus.OK,
#                 data=response_data
#             )

#         except Exception as e:
#             app.logger.exception(f"Unexpected error getting streams for event {event_id}")
#             return api_error(
#                 "Failed to retrieve livestreams",
#                 HTTPStatus.INTERNAL_SERVER_ERROR
#             )

#     @route("/scenes/<event_id>", methods=["DELETE"])
#     @jwt_required
#     async def end_livestream(self, event_id):
#         """
#         End and delete user's own livestream for an event.
#         Users can only delete their own streams.
#         """
#         # Validate event_id
#         if not self._validate_event_id(event_id):
#             return api_error("Invalid event ID format", HTTPStatus.BAD_REQUEST)

#         user_id = get_jwt_identity()

#         # Ensure client is initialized
#         try:
#             await self._ensure_scenes_client_initialized()
#         except Exception as e:
#             app.logger.error(f"Client initialization failed: {e}")
#             return api_error(
#                 "Streaming service unavailable",
#                 HTTPStatus.SERVICE_UNAVAILABLE
#             )

#         try:
#             # Check if user's stream exists
#             user_stream = await self.conn.fetch_cloudflare_scene(event_id, user_id)
#             if not user_stream:
#                 return api_error(
#                     "You don't have an active stream for this event",
#                     HTTPStatus.NOT_FOUND
#                 )

#             # Delete from Cloudflare
#             stream_deleted = await self.scenes_client.delete_stream(event_id, user_id)
            
#             # Delete from database
#             db_deleted = await self.conn.delete_cloudflare_scene(event_id, user_id)
            
#             if stream_deleted or db_deleted:
#                 # Invalidate cache
#                 try:
#                     await self.redis.delete(f"livestream:all:{event_id}")
#                     app.logger.info(f"Invalidated cache for event {event_id}")
#                 except redis.exceptions.RedisError as e:
#                     app.logger.error(f"Redis DELETE error: {e}")

#                 return api_response(
#                     "Stream deleted successfully",
#                     HTTPStatus.OK
#                 )
#             else:
#                 return api_error(
#                     "Stream not found",
#                     HTTPStatus.NOT_FOUND
#                 )

#         except APIError as e:
#             app.logger.error(f"Cloudflare API error deleting stream for user {user_id}, event {event_id}: {e}")
#             return api_response(
#                 f"Streaming provider error: {str(e)}",
#                 HTTPStatus.BAD_GATEWAY
#             )
#         except Exception as e:
#             app.logger.exception(f"Unexpected error deleting stream for user {user_id}, event {event_id}")
#             return api_error(
#                 "Failed to delete livestream",
#                 HTTPStatus.INTERNAL_SERVER_ERROR
#             )

#     @route("/scenes/<event_id>/report/<scene_id>", methods=["POST"])
#     @jwt_required
#     async def report_livestream(self, event_id, scene_id):
#         """
#         Report a livestream for violations or inappropriate content.
#         Any authenticated user can report a stream.
        
#         URL parameters:
#         - event_id: Event identifier
#         - scene_id: ID of the scene/stream being reported
        
#         Request body must include:
#         - reason: Description of why the stream is being reported
#         """
#         # Validate event_id
#         if not self._validate_event_id(event_id):
#             return api_error("Invalid event ID format", HTTPStatus.BAD_REQUEST)

#         reporter = get_jwt_identity()
#         data = await request.get_json()
#         reason = data.get("reason", "")
        
#         if not reason:
#             return api_error("Reason is required", HTTPStatus.BAD_REQUEST)

#         # Check if the livestream/scene exists
#         try:
#             async with self.conn.pool.acquire() as conn:
#                 scene_info = await conn.query(
#                     "SELECT * FROM ONLY type::thing('scenes', $scene_id);",
#                     {"scene_id": scene_id}
#                 )
#             if not scene_info:
#                 return api_error("Livestream not found", HTTPStatus.NOT_FOUND)
            
#             # Create report
#             if result := await self.conn._report_resource(
#                 {"reason": reason, "reporter": reporter, "resource": scene_info["id"]}
#             ):
#                 return api_response(
#                     "Livestream reported successfully",
#                     HTTPStatus.CREATED,
#                     data=result
#                 )
            
#             # If _report_resource returned falsy value
#             return api_error(
#                 "Failed to create report",
#                 HTTPStatus.INTERNAL_SERVER_ERROR
#             )
            
#         except Exception as e:
#             app.logger.exception(f"Error reporting livestream {event_id}")
#             return api_error(
#                 f"Failed to report livestream: {str(e)}",
#                 HTTPStatus.INTERNAL_SERVER_ERROR
#             )

#     @route("/scenes/<event_id>", methods=["POST"])
#     @jwt_required
#     async def create_livestream(self, event_id):
#         """
#         Create a livestream for a given event using Cloudflare Stream.

#         Cloudflare livestream creation workflow:
#         1. Validate event ID and user permissions
#         2. Create a Stream Input: Initializes a new livestream for the specified event
#         3. Store Stream Input: Stores the stream credentials in database
#         4. Return stream credentials to creator for OBS/streaming software

#         Args:
#             event_id (str): Unique identifier for the event to create a livestream for

#         Returns:
#             tuple: A JSON response containing stream information and HTTP status code
#                 - On success: (stream_info, HTTPStatus.CREATED)
#                 - On already exists: (stream_info, HTTPStatus.OK)
#                 - On failure: (error_message, appropriate HTTP status)
#         """
#         # Validate event_id
#         if not self._validate_event_id(event_id):
#             return api_error("Invalid event ID format", HTTPStatus.BAD_REQUEST)

#         # Check if user has permission (host or attendee) and event timing
#         user_id = get_jwt_identity()
#         has_permission, error_msg = await self._check_stream_permission(event_id, user_id)
#         if not has_permission:
#             return api_error(
#                 error_msg or "Unauthorized to create stream",
#                 HTTPStatus.FORBIDDEN
#             )

#         # Ensure client is initialized
#         try:
#             await self._ensure_scenes_client_initialized()
#         except Exception as e:
#             app.logger.error(f"Client initialization failed: {e}")
#             return api_error(
#                 "Streaming service unavailable",
#                 HTTPStatus.SERVICE_UNAVAILABLE
#             )

#         # Validate distance: host must be within 1km of event location
#         try:
#             data = await request.get_json()
#             if data and "coordinates" in data:
#                 async with self.conn.pool.acquire() as conn:
#                     # Fetch event information (OMIT duration to avoid CBOR parsing bug)
#                     event_info = await conn.query(
#                         "SELECT * OMIT duration FROM ONLY type::thing('events', $event_id);",
#                         {"event_id": event_id}
#                     )
                    
#                     if event_info and "location" in event_info:
#                         event_coordinates = event_info["location"].get("coordinates")
#                         host_coordinates = data["coordinates"]
#                         host_coordinates = shared.utils.coordinates_to_geometry_point(host_coordinates)
                        
#                         if not event_coordinates or not host_coordinates:
#                             return api_error(
#                                 "Coordinates are required for both event and livestream",
#                                 HTTPStatus.BAD_REQUEST
#                             )
                        
#                         # Calculate distance
#                         distance_result = await conn.query(
#                             "RETURN geo::distance($host_location, $event_location);",
#                             {
#                                 "host_location": host_coordinates,
#                                 "event_location": event_coordinates,
#                             },
#                         )
#                         distance_meters = float(distance_result) if distance_result else float('inf')
                        
#                         # Enforce 1km radius
#                         MAX_DISTANCE_METERS = 1000
#                         if distance_meters > MAX_DISTANCE_METERS:
#                             return api_error(
#                                 f"Host location is {distance_meters:.0f}m from event location (maximum: {MAX_DISTANCE_METERS}m). You must be at the event to go live.",
#                                 HTTPStatus.FORBIDDEN
#                             )
                        
#                         app.logger.info(f"Distance check passed: {distance_meters:.0f}m from event")
#                     else:
#                         app.logger.warning(f"Event {event_id} has no location data, skipping distance check")
#         except Exception as e:
#             app.logger.error(f"Distance validation error for event {event_id}: {e}")
#             # Don't block stream creation if distance check fails - log and continue
#             # In production, you might want to fail here depending on requirements

#         try:
#             # Check if user already has a stream for this event (idempotency)
#             existing_stream = await self.conn.fetch_cloudflare_scene(event_id, user_id)
#             if existing_stream:
#                 app.logger.info(f"User {user_id} already has a stream for event {event_id}")
#                 return api_response(
#                     "Stream already exists for this event",
#                     HTTPStatus.OK,
#                     data=[existing_stream] # Next build make this an object
#                 )

#             # Create new stream on Cloudflare
#             stream_create_resp = await self.scenes_client.create_stream(event_id, user_id)
#             if stream_create_resp:
#                 # Store stream in database with user association
#                 stream_info = await self.conn.store_cloudflare_scene(
#                     stream_create_resp, event_id, user_id
#                 )
                
#                 # Invalidate cache
#                 try:
#                     await self.redis.delete(f"livestream:all:{event_id}")
#                 except redis.exceptions.RedisError as e:
#                     app.logger.error(f"Redis cache invalidation error: {e}")
                
#                 app.logger.info(f"Successfully created stream for user {user_id} on event {event_id}")
#                 return api_response(
#                     "Stream created successfully",
#                     HTTPStatus.CREATED,
#                     data=stream_info
#                 )
#             else:
#                 app.logger.error(f"Stream creation returned false for user {user_id}, event {event_id}")
#                 return api_error(
#                     "Stream creation failed",
#                     HTTPStatus.INTERNAL_SERVER_ERROR
#                 )

#         except APIConnectionError as e:
#             app.logger.error(f"Cloudflare connection error for event {event_id}: {e}")
#             return api_response(
#                 f"Cannot connect to streaming provider: {str(e)}",
#                 HTTPStatus.SERVICE_UNAVAILABLE
#             )
#         except APITimeoutError as e:
#             app.logger.error(f"Cloudflare timeout error for event {event_id}: {e}")
#             return api_response(
#                 f"Streaming provider timeout: {str(e)}",
#                 HTTPStatus.GATEWAY_TIMEOUT
#             )
#         except APIError as e:
#             app.logger.error(f"Cloudflare API error for event {event_id}: {e}")
#             return api_response(
#                 f"Streaming provider error: {str(e)}",
#                 HTTPStatus.BAD_GATEWAY
#             )
#         except RuntimeError as e:
#             app.logger.error(f"Runtime error creating stream for event {event_id}: {e}")
#             return api_response(
#                 f"Service initialization error: {str(e)}",
#                 HTTPStatus.SERVICE_UNAVAILABLE
#             )
#         except Exception as e:
#             app.logger.exception(f"Unexpected error creating stream for event {event_id}")
#             return api_error(
#                 "Failed to create livestream",
#                 HTTPStatus.INTERNAL_SERVER_ERROR
#             )

#     # =========================================================================
#     # ALTERNATIVE IMPLEMENTATIONS (Not currently used)
#     # =========================================================================

#     # -------------------------------------------------------------------------
#     # VideoSDK Live Implementation
#     # -------------------------------------------------------------------------

#     @route("/scenes/get-token/<string:event_id>", methods=["POST"])
#     @jwt_required
#     async def generate_scene_token(self, event_id):
#         """
#         Generate VideoSDK token for live streaming.
#         NOTE: This is an alternative implementation, not currently used.
#         """
#         expiration = datetime.now() + timedelta(seconds=TOKEN_EXPIRATION_IN_SECONDS)
#         payload = {
#             "exp": expiration,
#             "apikey": VIDEOSDK_API_KEY,
#             "permissions": ["allow_join", "allow_mod"],
#         }

#         if event_id:
#             payload["version"] = 2
#             payload["roles"] = ["rtc"]
#             payload["roomId"] = event_id

#         token = jwt.encode(payload, VIDEOSDK_SECRET_KEY, algorithm="HS256")

#         return api_response(
#             "Token generated successfully",
#             HTTPStatus.OK,
#             data={"token": token}
#         )

