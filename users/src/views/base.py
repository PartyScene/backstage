from quart import request, current_app as app
from quart_jwt_extended import get_jwt_identity, jwt_required
from http import HTTPStatus
from typing import Tuple, Dict, Any
import asyncio
import uuid_utils as ruuid

from shared.classful import route, QuartClassful
from datetime import datetime
from users.src.connectors import UsersDB
from shared.workers.novu import NotificationManager
import os
import orjson as json
from aiocache import cached
from shared.workers.rmq import RMQBroker
from shared.utils import recursively_sign_object_media, api_response, api_error



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

    @route("/user", methods=["PATCH"])
    @jwt_required
    async def update_me(self):
        """Update current user information"""
        user_id = get_jwt_identity()  # Get user_id early for logging
        try:
            data = await request.get_json()
            if not data:
                return api_error("Request body required.", HTTPStatus.BAD_REQUEST)

            data["id"] = user_id  # Ensure ID is set for the update operation

            # Data checks
            if "kyc_payment_status" in data:
                data["kyc_payment_status"] = (
                    data.get("kyc_payment_status", "false") == "true"
                )

            result = await self.conn.update(data)
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
        """Get another user's public profile"""
        try:
            user = await self.conn.fetch(user_id)
            if not user:
                return api_error("User not found", HTTPStatus.NOT_FOUND)
            # Could filter sensitive information here if needed before returning
            # Example: user.pop('email', None)
            user = await recursively_sign_object_media(user)
            return api_response(
                "User profile fetched successfully.",
                HTTPStatus.OK,
                data=user
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching user profile ({user_id}): {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to fetch user profile: {str(e)}",
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
