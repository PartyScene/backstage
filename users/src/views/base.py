from quart import request, current_app as app
from quart_jwt_extended import get_jwt_identity, jwt_required
from http import HTTPStatus
from typing import Tuple, Dict, Any, List, Optional
import asyncio
import uuid_utils as ruuid

from shared.classful import route, QuartClassful
from datetime import datetime
from users.src.connectors import (
    UsersDB,
    HOST_GALLERY_MAX_ITEMS,
    PROFILE_SLUG_MIN_LEN,
    SlugConflictError,
)
from shared.workers.novu import NotificationManager
import os
import orjson as json
from aiocache import cached
from shared.workers.rmq import RMQBroker
from shared.utils import recursively_sign_object_media, api_response, api_error
from shared.kpi import BusinessMetrics


# Fields the client may set on PATCH /user. Anything outside this set is
# ignored so the endpoint cannot be used to escalate verification flags or
# overwrite server-managed columns (host_since, kyc_status, hashed_*, etc.).
HOST_PROFILE_EDITABLE_FIELDS = {
    "first_name", "last_name", "username", "organization_name",
    "bio", "sharedLoc",
    "profile_slug", "organization_type", "socials",
    "kyc_payment_status",  # already accepted by the previous handler
}

# Maximum sizes for free-text host profile fields. Keep generous but bounded so
# a malicious client cannot bloat the user document.
BIO_MAX_LEN = 500
SOCIAL_HANDLE_MAX_LEN = 100
SOCIAL_URL_MAX_LEN = 512
ORG_TYPE_MAX_LEN = 50



class BaseView(QuartClassful):
    def __init__(self):
        self.conn: UsersDB = app.conn
        self.redis = app.redis

        self.__notification_manager = NotificationManager()

    @route("/", methods=["GET"])
    async def index(self):
        return await self.healthcheck()


    @route("/users/upload", methods=["POST"])
    @jwt_required
    async def upload_media(self):
        """
        Uploads a file (e.g., avatar) to the Media Microservice via RMQ
        and triggers an update to the user's profile (e.g., avatar URL).
        """
        user_id = get_jwt_identity()  # Get user_id early for logging
        try:
            
            file = next((f for f in (await request.files).values() if f.filename), None)

            if not file or not file.filename:
                status_code = HTTPStatus.BAD_REQUEST
                return api_error(
                    "No file provided or file has no name.",
                    status_code,
                )

            # Prepare data for RMQ message and potential DB update
            # The actual user update (e.g., setting avatar URL) should happen
            # AFTER the media service confirms successful upload, possibly via
            # another RMQ message or direct API call from media service.
            # This endpoint primarily triggers the upload process.

            rmq_data = {
                "filename": f"users/{user_id}/{str(ruuid.uuid4()).split('-')[-1]}{os.path.splitext(file.filename)[-1]}",  # Define storage path
                "type": file.content_type,
                "creator": user_id,
                "context": "user_avatar",  # Add context for media service
                "user_id_to_update": user_id,  # Tell media service which user to notify/update later
            }
            app.logger.warning(
                f"Publishing user media upload task to RMQ: {rmq_data['filename']}"
            )

            # Publish task to RabbitMQ
            await app.RMQ._publish_media(rmq_data, file)

            # Don't update user profile here directly. Wait for confirmation.
            response = await self.conn.update(
                {
                    "id": user_id,
                    "filename": rmq_data["filename"],
                    "type": rmq_data["type"],
                }
            )  # Maybe set a pending status?

            # Return success indicating the upload process has started
            status_code = HTTPStatus.ACCEPTED  # 202 Accepted is suitable here
            return api_response(
                "Media upload process initiated successfully.",
                status_code,
                data=response,
            )  # 202 Accepted is suitable here

        except Exception as e:
            app.logger.error(
                f"Error initiating media upload for user {user_id}: {str(e)}",
                exc_info=True,
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return api_error(
                f"Failed to initiate media upload: {str(e)}",
                status_code,
            )


    @route("/users/search", methods=["GET"])
    @jwt_required
    async def search_user(self):
        """Search for users by username (implementation pending)"""
        username = request.args.get("username")
        if not username:
            status_code = HTTPStatus.BAD_REQUEST
            return api_error(
                "Username query parameter is required.",
                status_code,
            )
        # Add search logic here using self.conn
        # result = await self.conn.search_by_username(username)
        # status_code = HTTPStatus.OK
        status_code = HTTPStatus.NOT_IMPLEMENTED
        return api_error(
            "Search endpoint not yet implemented.",
            status_code,
        )

    @route("/users/blocked", methods=["GET"])
    @jwt_required
    async def get_blocked_users(self):
        """Fetch all users blocked by the current user"""
        user_id = get_jwt_identity()
        try:
            blocked_users = await self.conn.get_blocked_users(user_id)
            if not blocked_users:
                status_code = HTTPStatus.OK
                return api_response(
                    "No blocked users found",
                    status_code,
                )

            status_code = HTTPStatus.OK
            return api_response(
                "Blocked users fetched successfully.",
                status_code,
                data=blocked_users,
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching blocked users for user ({user_id}): {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return api_error(
                f"Failed to fetch blocked users: {str(e)}",
                status_code,
            )

    @route("/users/health", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def healthcheck(self):
        """
        Simple health check endpoint that verifies service and dependency status.
        Returns 200 OK if everything is healthy, 503 Service Unavailable otherwise.
        """
        health_status = {
            "service": "microservices.users",
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "dependencies": {"database": "unknown", "redis": "unknown"},
        }
        message = "Service is healthy"
        status_code = HTTPStatus.OK

        # Check database connection
        try:
            db_info = await self.conn._info()
            health_status["dependencies"]["database"] = "healthy"
        except Exception as e:
            app.logger.error(f"Database health check failed: {e}")
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
            app.logger.error(f"Redis health check failed: {e}")
            health_status["dependencies"]["redis"] = "unhealthy"
            health_status["status"] = "degraded"
            message = "Service degraded: Redis connection failed"
            status_code = HTTPStatus.SERVICE_UNAVAILABLE

        return api_response(message, status_code, data=health_status)

    @route("/user/tickets", methods=["GET"])
    @jwt_required
    async def get_tickets(self):
        user_id = get_jwt_identity()
        try:
            tickets = await self.conn.fetch_user_tickets(user_id)
            if not tickets:
                return api_response("No tickets found", HTTPStatus.OK)

            return api_response(
                "User tickets fetched successfully.",
                HTTPStatus.OK,
                data=tickets
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching user tickets ({user_id}): {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to fetch user tickets: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/user/events", methods=["GET"])
    @jwt_required
    async def get_user_events(self):
        """Fetch events attended or created by this user"""
        user_id = get_jwt_identity()
        created = request.args.get("created") == "true"
        try:
            events = await self.conn.fetch_user_events(user_id, created=created)
            if not events:
                return api_response("No events found", HTTPStatus.NOT_FOUND)

            return api_response(
                "User events fetched successfully.",
                HTTPStatus.OK,
                data=events
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching user events ({user_id}): {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to fetch user events: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/user", methods=["GET"])
    @jwt_required
    async def get_me(self):
        """Get current user details including friend connections and attended events"""
        user_id = get_jwt_identity()  # Get user_id early for logging
        app.logger.warning(f"GET /user JWT identity={user_id!r} type={type(user_id).__name__}")
        try:
            user = await self.conn.fetch(user_id)
            if not user:
                return api_error("User not found", HTTPStatus.NOT_FOUND)
            
            user = await recursively_sign_object_media(user)
            return api_response(
                "User details fetched successfully.",
                HTTPStatus.OK,
                data=user
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching current user ({user_id}): {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to fetch user details: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/user", methods=["DELETE"])
    @jwt_required
    async def delete_me(self):
        """Delete current user and their relationships"""
        user_id = get_jwt_identity()  # Get user_id early for logging
        try:
            result = await self.conn.delete(user_id)
            if not result:  # Assuming delete returns None or False if user not found
                return api_error("User not found", HTTPStatus.NOT_FOUND)
            # Consider triggering cleanup tasks (e.g., delete associated data in other services)
            return api_response("User deleted successfully", HTTPStatus.OK)
        except Exception as e:
            app.logger.error(
                f"Error deleting current user ({user_id}): {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to delete user: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    async def _validate_host_profile_patch(
        self, data: Dict[str, Any], user_id: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[str, int]]]:
        """
        Whitelist + validate fields for PATCH /user.

        Returns (clean_payload, None) on success or (None, (msg, status)) on
        failure. Any field outside HOST_PROFILE_EDITABLE_FIELDS is dropped.
        Server-managed fields (host_since, is_verified_host, cover_image, etc.)
        must be set through their dedicated endpoints, not here.
        """
        clean: Dict[str, Any] = {}

        # Drop unknown keys silently rather than 400ing — older clients may
        # send extra fields and we don't want to break them. Validation only
        # runs on keys the client may actually edit.
        for key, value in data.items():
            if key in HOST_PROFILE_EDITABLE_FIELDS:
                clean[key] = value

        # bio
        if "bio" in clean:
            if not isinstance(clean["bio"], str):
                return None, ("`bio` must be a string.", HTTPStatus.BAD_REQUEST)
            if len(clean["bio"]) > BIO_MAX_LEN:
                return None, (
                    f"`bio` exceeds {BIO_MAX_LEN} characters.", HTTPStatus.BAD_REQUEST
                )

        # organization_type
        if "organization_type" in clean and clean["organization_type"] is not None:
            ot = clean["organization_type"]
            if not isinstance(ot, str) or len(ot) > ORG_TYPE_MAX_LEN:
                return None, (
                    f"`organization_type` must be a string up to {ORG_TYPE_MAX_LEN} chars.",
                    HTTPStatus.BAD_REQUEST,
                )

        # profile_slug — only a shape check here. The actual normalization
        # (string::slug) and uniqueness check happen in
        # UsersDB.set_profile_slug, called separately by update_me so we don't
        # mix raw user input into the MERGE payload.
        if "profile_slug" in clean and clean["profile_slug"] is not None:
            if not UsersDB.is_valid_slug_input(clean["profile_slug"]):
                return None, (
                    f"`profile_slug` must be a string of at least "
                    f"{PROFILE_SLUG_MIN_LEN} non-whitespace characters.",
                    HTTPStatus.BAD_REQUEST,
                )

        # socials — flexible object, but values are bounded strings or list of
        # {label, url} for the `custom` key.
        if "socials" in clean and clean["socials"] is not None:
            socials = clean["socials"]
            if not isinstance(socials, dict):
                return None, ("`socials` must be an object.", HTTPStatus.BAD_REQUEST)

            for platform, value in socials.items():
                if not isinstance(platform, str) or not platform:
                    return None, (
                        "`socials` keys must be non-empty strings.",
                        HTTPStatus.BAD_REQUEST,
                    )

                if platform == "custom":
                    if not isinstance(value, list):
                        return None, (
                            "`socials.custom` must be a list of {label, url}.",
                            HTTPStatus.BAD_REQUEST,
                        )
                    for entry in value:
                        if (
                            not isinstance(entry, dict)
                            or not isinstance(entry.get("label"), str)
                            or not isinstance(entry.get("url"), str)
                            or len(entry["label"]) > SOCIAL_HANDLE_MAX_LEN
                            or len(entry["url"]) > SOCIAL_URL_MAX_LEN
                        ):
                            return None, (
                                "Invalid entry in `socials.custom`.",
                                HTTPStatus.BAD_REQUEST,
                            )
                    continue

                if value is None:
                    continue  # explicit clear of a platform handle
                if not isinstance(value, str):
                    return None, (
                        f"`socials.{platform}` must be a string.",
                        HTTPStatus.BAD_REQUEST,
                    )
                limit = SOCIAL_URL_MAX_LEN if value.startswith(("http://", "https://")) else SOCIAL_HANDLE_MAX_LEN
                if len(value) > limit:
                    return None, (
                        f"`socials.{platform}` exceeds {limit} characters.",
                        HTTPStatus.BAD_REQUEST,
                    )

        # kyc_payment_status was historically accepted as a "true"/"false"
        # string, keep that coercion working for older clients.
        if "kyc_payment_status" in clean and isinstance(clean["kyc_payment_status"], str):
            clean["kyc_payment_status"] = clean["kyc_payment_status"] == "true"

        return clean, None

    @route("/user", methods=["PATCH"])
    @jwt_required
    async def update_me(self):
        """Update current user information"""
        user_id = get_jwt_identity()  # Get user_id early for logging
        try:
            data = await request.get_json()
            if not data:
                return api_error("Request body required.", HTTPStatus.BAD_REQUEST)

            clean, err = await self._validate_host_profile_patch(data, user_id)
            if err:
                msg, status = err
                return api_error(msg, status)

            # Slug goes through string::slug normalization + uniqueness in a
            # dedicated query, so we pop it from the MERGE payload and only
            # apply it after the DB has accepted the normalized value. If the
            # slug fails we abort BEFORE merging the rest, preventing a
            # half-applied profile update.
            slug_input = clean.pop("profile_slug", None)
            if slug_input is not None:
                try:
                    await self.conn.set_profile_slug(user_id, slug_input)
                except SlugConflictError as ce:
                    return api_error(str(ce), HTTPStatus.CONFLICT)
                except ValueError as ve:
                    return api_error(str(ve), HTTPStatus.BAD_REQUEST)

            clean["id"] = user_id  # Ensure ID is set for the update operation

            result = await self.conn.update(clean) if (
                # Only call MERGE if there's something else to update.
                {k for k in clean.keys() if k != "id"}
            ) else await self.conn.fetch(user_id)
            if not result:  # Handle case where update fails or user doesn't exist
                # Check if user exists first? Might be redundant if update handles it.
                return api_error(
                    "User not found or update failed.",
                    HTTPStatus.NOT_FOUND
                )  # Or BAD_REQUEST?

            return api_response(
                "User updated successfully.",
                HTTPStatus.OK,
                data=result
            )
        except Exception as e:
            app.logger.error(
                f"Error updating current user ({user_id}): {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to update user: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/users/<user_id>", methods=["GET"])
    @jwt_required
    async def get_user(self, user_id: str):
        """Get another user's public host profile (aggregated)."""
        viewer_id = get_jwt_identity()
        app.logger.warning(f"GET /users/{user_id} viewer={viewer_id!r}")
        try:
            profile = await self.conn.fetch_host_profile(user_id, viewer_id=viewer_id)
            if not profile:
                return api_error("User not found", HTTPStatus.NOT_FOUND)
            profile = await recursively_sign_object_media(profile)
            return api_response(
                "User profile fetched successfully.",
                HTTPStatus.OK,
                data=profile,
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching user profile ({user_id}): {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to fetch user profile: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/host/<slug>", methods=["GET"])
    @jwt_required
    async def get_host_by_slug(self, slug: str):
        """
        Resolve a host's profile_slug and return the same shape as
        GET /users/<user_id>. We resolve the slug first so the aggregate query
        runs against a known-good user id rather than a slug filter.
        """
        viewer_id = get_jwt_identity()
        try:
            user = await self.conn.fetch_by_slug(slug)
            if not user:
                return api_error("Host not found", HTTPStatus.NOT_FOUND)

            user_id = str(user["id"]).split(":")[-1]
            profile = await self.conn.fetch_host_profile(user_id, viewer_id=viewer_id)
            if not profile:
                return api_error("Host not found", HTTPStatus.NOT_FOUND)
            profile = await recursively_sign_object_media(profile)
            return api_response(
                "Host profile fetched successfully.",
                HTTPStatus.OK,
                data=profile,
            )
        except Exception as e:
            app.logger.error(
                f"Error resolving host slug {slug}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to fetch host profile: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/users/<user_id>/report", methods=["POST"])
    @jwt_required
    async def report_user(self, user_id):
        """This endpoints reports a specific user"""
        reporter = get_jwt_identity()
        data = await request.get_json()
        reason = data.get("reason", "")
        if not reason:
            return api_error("Reason is required", HTTPStatus.BAD_REQUEST)

        # Check if the event exists

        user_info = await self.conn.fetch(user_id)
        if not user_info:
            return api_error("User not found", HTTPStatus.NOT_FOUND)

        if result := await self.conn._report_resource(
            {"reason": reason, "reporter": reporter, "resource": user_info["id"]}
        ):
            status_code = HTTPStatus.CREATED
            return api_response(
                "Resource reported",
                status_code,
                data=result,
            )

    @route("/users/<user_id>/block", methods=["POST"])
    @jwt_required
    async def block_user(self, user_id: str):
        """Block a specific user"""
        blocker_id = get_jwt_identity()
        try:
            # Prevent self-blocking
            if blocker_id == user_id:
                status_code = HTTPStatus.BAD_REQUEST
                return api_error(
                    "Cannot block yourself.",
                    status_code,
                )

            # Check if the user to be blocked exists
            user_info = await self.conn.fetch(user_id)
            if not user_info:
                status_code = HTTPStatus.NOT_FOUND
                return api_error(
                    "User not found",
                    status_code,
                )

            # Create the block relationship
            result = await self.conn.block_user(blocker_id, user_id)
            
            status_code = HTTPStatus.CREATED
            return api_response(
                "User blocked successfully.",
                status_code,
                data=result,
            )

        except Exception as e:
            app.logger.error(
                f"Error blocking user {user_id} by {blocker_id}: {str(e)}", 
                exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return api_error(
                f"Failed to block user: {str(e)}",
                status_code,
            )

    @route("/users/<user_id>/block", methods=["DELETE"])
    @jwt_required
    async def unblock_user(self, user_id: str):
        """Unblock a specific user"""
        blocker_id = get_jwt_identity()
        try:
            # Remove the block relationship
            result = await self.conn.unblock_user(blocker_id, user_id)
            
            if result:
                status_code = HTTPStatus.OK
                return api_response(
                    "User unblocked successfully.",
                    status_code,
                    data=result,
                )
            else:
                status_code = HTTPStatus.NOT_FOUND
                return api_error(
                    "Block relationship not found.",
                    status_code,
                )

        except Exception as e:
            app.logger.error(
                f"Error unblocking user {user_id} by {blocker_id}: {str(e)}", 
                exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return api_error(
                f"Failed to unblock user: {str(e)}",
                status_code,
            )



    @route("/friends", methods=["GET"])
    @jwt_required
    async def get_connections_at_degree(self):  # Removed extra bracket
        """
        Get all connections up to N degrees of separation

        Query Parameters:
            max_degree (int): Maximum degree of separation (1-6, default: 1)
        """
        user_id = get_jwt_identity()  # Get user_id early for logging
        try:
            max_degree = request.args.get(
                "max_degree", type=int, default=1
            )  # Default to 1

            if not 1 <= max_degree <= 6:
                status_code = HTTPStatus.BAD_REQUEST
                return api_error(
                    "max_degree must be between 1 and 6",
                    status_code,
                )

            result = await self.conn.get_connections_at_degree(user_id, max_degree)
            status_code = HTTPStatus.OK
            return api_response(
                f"Connections up to degree {max_degree} fetched.",
                status_code,
                data=result,
            )
        except ValueError:  # Catch potential type error for max_degree
            status_code = HTTPStatus.BAD_REQUEST
            return api_error(
                "Invalid value for max_degree parameter.",
                status_code,
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching connections for user {user_id}: {str(e)}",
                exc_info=True,
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return api_error(
                f"Failed to fetch connections: {str(e)}",
                status_code,
            )

    @route("/friends", methods=["POST"])
    @jwt_required
    async def create_connection(self):
        """Create a friendship connection (friend request) with another user"""
        try:
            data: dict = await request.get_json()
            target_id = data.get("target_id")
            if not target_id:
                status_code = HTTPStatus.BAD_REQUEST
                return api_error(
                    "target_id is required in request body.",
                    status_code,
                )

            data["origin_id"] = get_jwt_identity()

            # Prevent self-friending
            if data["origin_id"] == target_id:
                status_code = HTTPStatus.BAD_REQUEST
                return api_error(
                    "Cannot send friend request to yourself.",
                    status_code,
                )

            if result := await self.conn.create_friend_relationship(data):
                BusinessMetrics.FRIEND_REQUESTS.inc()
                app.logger.info(
                    f"Friend request created: {json.dumps(result, option=json.OPT_INDENT_2, default=str)}"
                )
                # Ensure result structure is as expected before accessing indices/keys
                notification_sent = False
                if isinstance(result, dict) and "in" in result and "out" in result:
                    try:
                        sender = await self.conn.fetch(result["in"])
                        await self.__notification_manager.send_friend_request_notification(
                            recipient_id=result["out"], sender_name=sender["organization_name"] or sender["first_name"]
                        )
                        notification_sent = True
                    except Exception as notify_err:
                        app.logger.error(
                            f"Failed to send friend request notification: {notify_err}"
                        )

                status_code = HTTPStatus.CREATED
                message = (
                    "Friend request sent successfully."
                    if notification_sent
                    else "Friend request created, but notification failed."
                )
                return api_response(
                    message,
                    status_code,
                    data=result,
                )

            # Handle case where connector returns non-truthy without exception
            app.logger.warning(
                f"Failed to create friend request between {data['origin_id']} and {target_id} (connector returned non-truthy)"
            )
            status_code = HTTPStatus.BAD_REQUEST  # Or CONFLICT?
            return api_error(
                "Failed to create friend request (e.g., already exists or invalid IDs).",
                status_code,
            )  # Or CONFLICT?

        except Exception as e:
            app.logger.error(f"Error creating friend request: {str(e)}", exc_info=True)
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return api_error(
                f"Failed to send friend request: {str(e)}",
                status_code,
            )

    @route("/friends/<connection_id>", methods=["PATCH"])
    @jwt_required
    async def update_connection(self, connection_id: str):
        """
        Update the connection status between two users (accept/block request)
        """
        try:
            data: dict = await request.get_json()
            new_status = data.get("status")

            if not new_status:
                status_code = HTTPStatus.BAD_REQUEST
                return api_error(
                    "Status is required in request body.",
                    status_code,
                )

            # Add validation for allowed statuses ('accepted', 'blocked')?
            allowed_statuses = [
                "accepted",
                "blocked",
                "pending",
                "removed",
                "rejected",
                
            ]  # Include pending if needed
            if new_status not in allowed_statuses:
                status_code = HTTPStatus.BAD_REQUEST
                return api_error(
                    f"Invalid status. Must be one of: {', '.join(allowed_statuses)}",
                    status_code,
                )

            # TODO: Add authorization check - verify current user is recipient of friend request
            result = await self.conn.update_friend_relationship(connection_id, data)
            if result:  # Assuming update returns the updated connection or True
                # Send notification on acceptance/block?
                # if new_status == "accepted":
                #     await self.__notification_manager.send_friend_request_accepted_notification(...)
                status_code = HTTPStatus.OK
                return api_response(
                    "Connection status updated successfully.",
                    status_code,
                    data=result,
                )
            else:
                app.logger.warning(
                    f"Failed to update connection {connection_id} (connector returned non-truthy)"
                )
                status_code = HTTPStatus.NOT_FOUND
                return api_error(
                    "Connection not found or update failed.",
                    status_code,
                )

        except Exception as e:
            app.logger.error(
                f"Error updating connection {connection_id}: {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return api_error(
                f"Failed to update connection: {str(e)}",
                status_code,
            )

    @route("/friends/<connection_id>", methods=["DELETE"])
    @jwt_required
    async def delete_connection(self, connection_id: str):
        """Delete a friendship connection or cancel/reject a request"""
        try:
            # TODO: Add authorization check - verify current user is part of connection
            result = await self.conn.update_friend_relationship(connection_id, {"status": "removed"})
            if result:  # Assuming delete returns True or affected count > 0
                status_code = HTTPStatus.OK
                return api_response(
                    "Connection deleted successfully.",
                    status_code,
                )
            else:
                app.logger.warning(
                    f"Connection {connection_id} not found or deletion failed."
                )
                status_code = HTTPStatus.NOT_FOUND
                return api_error(
                    "Connection not found or could not be deleted.",
                    status_code,
                )

        except Exception as e:
            app.logger.error(
                f"Error deleting connection {connection_id}: {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return api_error(
                f"Failed to delete connection: {str(e)}",
                status_code,
            )

    # ------------------------------------------------------------------
    # Host follower endpoints
    # ------------------------------------------------------------------

    @route("/users/<user_id>/follow", methods=["POST"])
    @jwt_required
    async def follow_host(self, user_id: str):
        """Follow a host. Idempotent: a duplicate follow returns 200 OK with
        the existing edge instead of erroring."""
        follower_id = get_jwt_identity()
        try:
            target = await self.conn.fetch(user_id)
            if not target:
                return api_error("User not found", HTTPStatus.NOT_FOUND)

            edge = await self.conn.follow_host(follower_id, user_id)
            return api_response(
                "Followed host.",
                HTTPStatus.CREATED,
                data=edge,
            )
        except ValueError as ve:
            return api_error(str(ve), HTTPStatus.BAD_REQUEST)
        except Exception as e:
            app.logger.error(
                f"Error following host {user_id} from {follower_id}: {e}",
                exc_info=True,
            )
            return api_error(
                f"Failed to follow host: {e}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @route("/users/<user_id>/follow", methods=["DELETE"])
    @jwt_required
    async def unfollow_host(self, user_id: str):
        """Unfollow a host. Returns 200 OK whether or not the edge existed —
        clients calling unfollow on a non-followed host shouldn't see 404."""
        follower_id = get_jwt_identity()
        try:
            removed = await self.conn.unfollow_host(follower_id, user_id)
            return api_response(
                "Unfollowed host." if removed else "Not following host.",
                HTTPStatus.OK,
                data=removed,
            )
        except Exception as e:
            app.logger.error(
                f"Error unfollowing host {user_id} from {follower_id}: {e}",
                exc_info=True,
            )
            return api_error(
                f"Failed to unfollow host: {e}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    # ------------------------------------------------------------------
    # Cover image upload
    # ------------------------------------------------------------------

    @route("/users/upload/cover", methods=["POST"])
    @jwt_required
    async def upload_cover(self):
        """Upload a host cover image. Mirrors POST /users/upload (avatar) but
        stores under /covers/ and points users.cover_image at the new media."""
        user_id = get_jwt_identity()
        try:
            file = next(
                (f for f in (await request.files).values() if f.filename),
                None,
            )
            if not file or not file.filename:
                return api_error(
                    "No file provided or file has no name.",
                    HTTPStatus.BAD_REQUEST,
                )

            ext = os.path.splitext(file.filename)[-1]
            filename = (
                f"users/{user_id}/covers/"
                f"{str(ruuid.uuid4()).split('-')[-1]}{ext}"
            )
            content_type = file.content_type

            # Persist the media row + user reference first so the response
            # can include the canonical media id even before RMQ finishes.
            persisted = await self.conn.set_cover_media(
                user_id=user_id,
                filename=filename,
                content_type=content_type,
            )

            media_id = str(persisted["media"]["id"]).split(":")[-1]
            rmq_data = {
                "filename": filename,
                "type": content_type,
                "creator": user_id,
                "context": "user_cover",
                "media_id": media_id,
                "user_id_to_update": user_id,
            }
            app.logger.warning(
                f"Publishing cover upload to RMQ: {rmq_data['filename']}"
            )
            await app.RMQ._publish_media(rmq_data, file)

            return api_response(
                "Cover upload initiated.",
                HTTPStatus.ACCEPTED,
                data=persisted,
            )
        except Exception as e:
            app.logger.error(
                f"Error uploading cover for user {user_id}: {e}", exc_info=True
            )
            return api_error(
                f"Failed to upload cover: {e}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    # ------------------------------------------------------------------
    # Host gallery endpoints
    # ------------------------------------------------------------------

    @route("/host/media", methods=["POST"])
    @jwt_required
    async def add_host_media(self):
        """
        Upload a single gallery image for the current host.

        Multipart form fields:
            file (required): image file
            caption (optional): up to 280 chars
            event (optional): event id to associate

        The 20-item cap is enforced in the connector. RMQ runs the same
        compression + metadata pipeline used for avatars/event media.
        """
        user_id = get_jwt_identity()
        try:
            files = await request.files
            file = next((f for f in files.values() if f.filename), None)
            if not file or not file.filename:
                return api_error(
                    "No file provided or file has no name.",
                    HTTPStatus.BAD_REQUEST,
                )

            form = await request.form
            caption = form.get("caption")
            event_id = form.get("event") or None
            if caption and len(caption) > 280:
                return api_error(
                    "`caption` must be 280 characters or fewer.",
                    HTTPStatus.BAD_REQUEST,
                )

            ext = os.path.splitext(file.filename)[-1]
            filename = (
                f"users/{user_id}/gallery/"
                f"{str(ruuid.uuid4()).split('-')[-1]}{ext}"
            )
            content_type = file.content_type

            persisted = await self.conn.add_gallery_media(
                user_id=user_id,
                filename=filename,
                content_type=content_type,
                caption=caption,
                event_id=event_id,
            )

            media_id = str(persisted["media"]["id"]).split(":")[-1]
            rmq_data = {
                "filename": filename,
                "type": content_type,
                "creator": user_id,
                "context": "host_gallery",
                "media_id": media_id,
            }
            app.logger.warning(
                f"Publishing gallery upload to RMQ: {rmq_data['filename']}"
            )
            await app.RMQ._publish_media(rmq_data, file)

            return api_response(
                "Gallery upload initiated.",
                HTTPStatus.ACCEPTED,
                data=persisted,
            )
        except ValueError as ve:
            # 20-item cap or similar input failure
            return api_error(str(ve), HTTPStatus.BAD_REQUEST)
        except Exception as e:
            app.logger.error(
                f"Error adding gallery media for {user_id}: {e}", exc_info=True
            )
            return api_error(
                f"Failed to add gallery media: {e}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @route("/host/media/<media_id>", methods=["DELETE"])
    @jwt_required
    async def delete_host_media(self, media_id: str):
        """Remove a gallery item the caller owns. Only the host_media edge is
        deleted; the underlying media row is preserved because it may still be
        referenced (cover, posts, events)."""
        user_id = get_jwt_identity()
        try:
            removed = await self.conn.remove_gallery_media(user_id, media_id)
            if not removed:
                return api_error(
                    "Gallery item not found for this host.", HTTPStatus.NOT_FOUND
                )
            return api_response("Gallery item removed.", HTTPStatus.OK)
        except Exception as e:
            app.logger.error(
                f"Error removing gallery media {media_id} for {user_id}: {e}",
                exc_info=True,
            )
            return api_error(
                f"Failed to remove gallery media: {e}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @route("/host/media/reorder", methods=["PUT"])
    @jwt_required
    async def reorder_host_media(self):
        """Replace the caller's gallery ordering with the supplied list of
        media ids. Ownership is verified inside the connector so we 400 instead
        of leaking another host's ids."""
        user_id = get_jwt_identity()
        try:
            data = await request.get_json() or {}
            ordered: List[str] = data.get("order") or []
            if not isinstance(ordered, list) or any(
                not isinstance(x, str) for x in ordered
            ):
                return api_error(
                    "`order` must be a list of media ids.",
                    HTTPStatus.BAD_REQUEST,
                )
            if len(ordered) > HOST_GALLERY_MAX_ITEMS:
                return api_error(
                    f"`order` exceeds {HOST_GALLERY_MAX_ITEMS} items.",
                    HTTPStatus.BAD_REQUEST,
                )

            updated = await self.conn.reorder_gallery(user_id, ordered)
            return api_response(
                "Gallery reordered.",
                HTTPStatus.OK,
                data=updated,
            )
        except ValueError as ve:
            return api_error(str(ve), HTTPStatus.BAD_REQUEST)
        except Exception as e:
            app.logger.error(
                f"Error reordering gallery for {user_id}: {e}", exc_info=True
            )
            return api_error(
                f"Failed to reorder gallery: {e}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @route("/users/recommendations", methods=["GET"])
    @jwt_required
    async def get_friend_recommendations(self):
        """
        Returns a ranked list of people the current user might want to connect with.

        Powered by fn::recommend_friends — combines:
          - Visual similarity between posted photos (ViT-768 HNSW)
          - Shared event attendance history
          - Degree-2 mutual friend graph

        Query params:
            limit (int, optional):  Max results to return. Default 20, max 50.

        Response 200:
            {
                "message": "Recommendations fetched successfully.",
                "data": [
                    {
                        "user": {
                            "id": "users:abc123",
                            "first_name": "...",
                            "last_name": "...",
                            "username": "...",
                            "avatar": "...",
                            "organization_name": "..."
                        },
                        "score": 0.74,
                        "signals": {
                            "shared_events": 3,
                            "visual_similarity": 0.81,
                            "mutual_friends": 2
                        }
                    }
                ]
            }

        Notes:
            - Users with no processed media (r18e batcher pending) will still appear
              if they have social signals; visual_similarity will be 0.0 for them.
            - Results are cached per user for 10 minutes in Redis to avoid
              re-running the HNSW query on every feed refresh.
        """
        user_id = get_jwt_identity()

        # Clamp limit to a safe range — large limits increase HNSW query cost
        try:
            limit = min(int(request.args.get("limit", 20)), 50)
        except (ValueError, TypeError):
            return api_error("limit must be an integer.", HTTPStatus.BAD_REQUEST)

        # Cache key is per-user. TTL of 10 minutes balances freshness vs cost.
        # Invalidate on: new friend connection, new block, new event attendance.
        # (Those endpoints should call self.redis.delete(cache_key) if you want
        #  immediate invalidation — optional, stale-for-10min is acceptable here.)
        cache_key = f"recommendations:{user_id}:{limit}"

        try:
            # Check Redis cache first
            cached = await self.redis.get(cache_key)
            if cached:
                import orjson as json
                return api_response(
                    "Recommendations fetched successfully.",
                    HTTPStatus.OK,
                    data=json.loads(cached),
                )

            recommendations = await self.conn.recommend_friends(user_id, limit)

            if not recommendations:
                return api_response(
                    "No recommendations found yet. Connect with more people or upload photos to improve suggestions.",
                    HTTPStatus.OK,
                    data=[],
                )

            # Sign any media URLs in the response (avatar fields etc.)
            recommendations = await recursively_sign_object_media(recommendations)

            # Cache for 10 minutes
            import orjson as json
            await self.redis.setex(
                cache_key,
                600,  # 10 minutes TTL
                json.dumps(recommendations, default=str),
            )

            return api_response(
                "Recommendations fetched successfully.",
                HTTPStatus.OK,
                data=recommendations,
            )

        except Exception as e:
            app.logger.error(
                f"Error fetching friend recommendations for user {user_id}: {str(e)}",
                exc_info=True,
            )
            return api_error(
                f"Failed to fetch recommendations: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

