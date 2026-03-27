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
_stream_chat_client_lock = asyncio.Lock()


async def _get_chat_client() -> StreamChatAsync:
    """
    Return the StreamChatAsync singleton, creating it on first call.

    Uses an asyncio.Lock so two concurrent requests that both see None
    don't each create a StreamChatAsync — the second would silently replace
    the first and leak its aiohttp.TCPConnector.
    """
    global _stream_chat_client
    if _stream_chat_client is not None:
        return _stream_chat_client
    async with _stream_chat_client_lock:
        if _stream_chat_client is None:  # re-check inside lock
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
                        distance_m = float(distance_result) if distance_result is not None else float("inf")

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
            channel = (await _get_chat_client()).channel(
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
            channel = (await _get_chat_client()).channel("livestream", call_id)
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
    # POST /scenes/<event_id>/attendee-location
    # Called by the RN app periodically (e.g. every 60 s) and on foreground.
    # Checks whether the user is still within the party radius.
    # If outside → revoke attendee streaming role (demote to viewer).
    # If inside  → re-grant (handles the case they briefly stepped out).
    # ------------------------------------------------------------------

    @route("/scenes/<event_id>/attendee-location", methods=["POST"])
    @jwt_required
    async def attendee_location_check(self, event_id: str):
        """
        Geofence check for the attendee streaming role.

        Body: { "coordinates": [lng, lat] }

        The RN app should call this:
          - Once per minute while the user is in the stream view
          - On app foreground resume
          - On GPS location update if > 100 m change

        Role management:
          - Inside radius (≤ 1000 m): user is/stays an "attendee" member on the call
          - Outside radius (> 1000 m): demoted to "viewer" — can still watch,
            cannot publish video
        """
        if not self._validate_event_id(event_id):
            return api_error("Invalid event ID format", HTTPStatus.BAD_REQUEST)

        user_id = get_jwt_identity()
        data = await request.get_json()

        if not data or "coordinates" not in data:
            return api_error("coordinates required", HTTPStatus.BAD_REQUEST)

        user_coords = coordinates_to_geometry_point(data["coordinates"])
        if not user_coords:
            return api_error("Invalid coordinates format", HTTPStatus.BAD_REQUEST)

        try:
            async with self.conn.pool.acquire() as conn:
                event_info = await conn.query(
                    "SELECT location, time, host FROM ONLY type::thing('events', $eid);",
                    {"eid": event_id},
                )

            if not event_info:
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            event_coords = (event_info.get("location") or {}).get("coordinates")
            if not event_coords:
                # No location set on event — can't enforce geofence, keep role as-is
                return api_response("No event location set — geofence skipped", HTTPStatus.OK,
                                    data={"inside": True})

            async with self.conn.pool.acquire() as conn:
                distance_result = await conn.query(
                    "RETURN geo::distance($user_location, $event_location);",
                    {"user_location": user_coords, "event_location": event_coords},
                )

            distance_m = float(distance_result) if distance_result is not None else float("inf")
            inside = distance_m <= 1000

            call_id = _call_id_for_event(event_id)
            call    = _stream_video_client.video.call("livestream", call_id)

            if inside:
                # (Re-)grant attendee role — idempotent on Stream's side
                await _run_sync(
                    call.update_call_members,
                    update_members=[MemberRequest(user_id=user_id, role="attendee")],
                )
                app.logger.info(f"✅ Attendee role active: user={user_id} dist={distance_m:.0f}m event={event_id}")
            else:
                # Demote to viewer — can watch, cannot publish
                await _run_sync(
                    call.update_call_members,
                    update_members=[MemberRequest(user_id=user_id, role="viewer")],
                )
                app.logger.info(f"⚠️ Attendee role revoked: user={user_id} dist={distance_m:.0f}m event={event_id}")

            return api_response(
                "Location checked",
                HTTPStatus.OK,
                data={"inside": inside, "distance_m": round(distance_m)},
            )

        except Exception as exc:
            app.logger.exception(f"attendee_location_check failed for {event_id}/{user_id}")
            return api_error("Location check failed", HTTPStatus.INTERNAL_SERVER_ERROR)

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