import httpx
from quart import request, current_app as app, jsonify
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
from shared.utils import recursively_sign_object_media



class BaseView(QuartClassful):
    def __init__(self):
        self.conn: UsersDB = app.conn
        self.redis = app.redis

        self.__notification_manager = NotificationManager()

    @route("/", methods=["GET"])
    async def index(self):
        return await self.healthcheck()

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

        return (
            jsonify(data=health_status, message=message, status=status_code.phrase),
            status_code,
        )

    @route("/user/tickets", methods=["GET"])
    @jwt_required
    async def get_tickets(self):
        user_id = get_jwt_identity()
        try:
            tickets = await self.conn.fetch_user_tickets(user_id)
            if not tickets:
                status_code = HTTPStatus.OK
                return (
                    jsonify(message="No tickets found", status=status_code.phrase),
                    status_code,
                )

            status_code = HTTPStatus.OK
            return (
                jsonify(
                    data=tickets,
                    message="User tickets fetched successfully.",
                    status=status_code.phrase,
                ),
                status_code,
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching user tickets ({user_id}): {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to fetch user tickets: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
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
                status_code = HTTPStatus.NOT_FOUND
                return (
                    jsonify(message="No events found", status=status_code.phrase),
                    status_code,
                )

            status_code = HTTPStatus.OK
            return (
                jsonify(
                    data=events,
                    message="User events fetched successfully.",
                    status=status_code.phrase,
                ),
                status_code,
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching user events ({user_id}): {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to fetch user events: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/user", methods=["GET"])
    @jwt_required
    async def get_me(self):
        """Get current user details including friend connections and attended events"""
        user_id = get_jwt_identity()  # Get user_id early for logging
        try:
            user = await self.conn.fetch(user_id)
            if not user:
                status_code = HTTPStatus.NOT_FOUND
                return (
                    jsonify(message="User not found", status=status_code.phrase),
                    status_code,
                )
            
            user = await recursively_sign_object_media(user)
            status_code = HTTPStatus.OK
            return (
                jsonify(
                    data=user,
                    message="User details fetched successfully.",
                    status=status_code.phrase,
                ),
                status_code,
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching current user ({user_id}): {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to fetch user details: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/user", methods=["DELETE"])
    @jwt_required
    async def delete_me(self):
        """Delete current user and their relationships"""
        user_id = get_jwt_identity()  # Get user_id early for logging
        try:
            result = await self.conn.delete(user_id)
            if not result:  # Assuming delete returns None or False if user not found
                status_code = HTTPStatus.NOT_FOUND
                return (
                    jsonify(message="User not found", status=status_code.phrase),
                    status_code,
                )
            # Consider triggering cleanup tasks (e.g., delete associated data in other services)
            status_code = HTTPStatus.OK
            return (
                jsonify(message="User deleted successfully", status=status_code.phrase),
                status_code,
            )
        except Exception as e:
            app.logger.error(
                f"Error deleting current user ({user_id}): {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to delete user: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/user", methods=["PATCH"])
    @jwt_required
    async def update_me(self):
        """Update current user information"""
        user_id = get_jwt_identity()  # Get user_id early for logging
        try:
            data = await request.get_json()
            if not data:
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="Request body required.", status=status_code.phrase
                    ),
                    status_code,
                )

            data["id"] = user_id  # Ensure ID is set for the update operation

            # Data checks
            if "kyc_payment_status" in data:
                data["kyc_payment_status"] = (
                    data.get("kyc_payment_status", "false") == "true"
                )

            result = await self.conn.update(data)
            if not result:  # Handle case where update fails or user doesn't exist
                # Check if user exists first? Might be redundant if update handles it.
                status_code = HTTPStatus.NOT_FOUND  # Or BAD_REQUEST?
                return (
                    jsonify(
                        message="User not found or update failed.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )  # Or BAD_REQUEST?

            status_code = HTTPStatus.OK
            return (
                jsonify(
                    data=result,
                    message="User updated successfully.",
                    status=status_code.phrase,
                ),
                status_code,
            )
        except Exception as e:
            app.logger.error(
                f"Error updating current user ({user_id}): {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to update user: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/users/<user_id>", methods=["GET"])
    @jwt_required
    async def get_user(self, user_id: str):
        """Get another user's public profile"""
        try:
            user = await self.conn.fetch(user_id)
            if not user:
                status_code = HTTPStatus.NOT_FOUND
                return (
                    jsonify(message="User not found", status=status_code.phrase),
                    status_code,
                )
            # Could filter sensitive information here if needed before returning
            # Example: user.pop('email', None)
            user = await recursively_sign_object_media(user)
            status_code = HTTPStatus.OK
            return (
                jsonify(
                    data=user,
                    message="User profile fetched successfully.",
                    status=status_code.phrase,
                ),
                status_code,
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching user profile ({user_id}): {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to fetch user profile: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/users/<user_id>/report", methods=["POST"])
    @jwt_required
    async def report_user(self, user_id):
        """This endpoints reports a specific user"""
        reporter = get_jwt_identity()
        data = await request.get_json()
        reason = data.get("reason", "")
        if not reason:
            status_code = HTTPStatus.BAD_REQUEST
            return (
                jsonify(message="Reason is required", status=status_code.phrase),
                status_code,
            )

        # Check if the event exists

        user_info = await self.conn.fetch(user_id)
        if not user_info:
            status_code = HTTPStatus.NOT_FOUND
            return (
                jsonify(message="User not found", status=status_code.phrase),
                status_code,
            )

        if result := await self.conn._report_resource(
            {"reason": reason, "reporter": reporter, "resource": user_info["id"]}
        ):
            status_code = HTTPStatus.CREATED
            return (
                jsonify(
                    message="Resource reported", data=result, status=status_code.phrase
                ),
                status_code,
            )

    @route("/users/search", methods=["GET"])
    @jwt_required
    async def search_user(self):
        """Search for users by username (implementation pending)"""
        username = request.args.get("username")
        if not username:
            status_code = HTTPStatus.BAD_REQUEST
            return (
                jsonify(
                    message="Username query parameter is required.",
                    status=status_code.phrase,
                ),
                status_code,
            )
        # Add search logic here using self.conn
        # result = await self.conn.search_by_username(username)
        # status_code = HTTPStatus.OK
        # return jsonify(data=result, message="Search results retrieved.", status=status_code.phrase), status_code
        status_code = HTTPStatus.NOT_IMPLEMENTED
        return (
            jsonify(
                message="Search endpoint not yet implemented.",
                status=status_code.phrase,
            ),
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
                return (
                    jsonify(
                        message="max_degree must be between 1 and 6",
                        status=status_code.phrase,
                    ),
                    status_code,
                )

            result = await self.conn.get_connections_at_degree(user_id, max_degree)
            status_code = HTTPStatus.OK
            return (
                jsonify(
                    data=result,
                    message=f"Connections up to degree {max_degree} fetched.",
                    status=status_code.phrase,
                ),
                status_code,
            )
        except ValueError:  # Catch potential type error for max_degree
            status_code = HTTPStatus.BAD_REQUEST
            return (
                jsonify(
                    message="Invalid value for max_degree parameter.",
                    status=status_code.phrase,
                ),
                status_code,
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching connections for user {user_id}: {str(e)}",
                exc_info=True,
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to fetch connections: {str(e)}",
                    status=status_code.phrase,
                ),
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
                return (
                    jsonify(
                        message="target_id is required in request body.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )

            data["origin_id"] = get_jwt_identity()

            # Prevent self-friending
            if data["origin_id"] == target_id:
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="Cannot send friend request to yourself.",
                        status=status_code.phrase,
                    ),
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
                            recipient_id=result["out"], sender_name=sender["first_name"]
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
                return (
                    jsonify(data=result, message=message, status=status_code.phrase),
                    status_code,
                )

            # Handle case where connector returns non-truthy without exception
            app.logger.warning(
                f"Failed to create friend request between {data['origin_id']} and {target_id} (connector returned non-truthy)"
            )
            status_code = HTTPStatus.BAD_REQUEST  # Or CONFLICT?
            return (
                jsonify(
                    message="Failed to create friend request (e.g., already exists or invalid IDs).",
                    status=status_code.phrase,
                ),
                status_code,
            )  # Or CONFLICT?

        except Exception as e:
            app.logger.error(f"Error creating friend request: {str(e)}", exc_info=True)
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to send friend request: {str(e)}",
                    status=status_code.phrase,
                ),
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
                return (
                    jsonify(
                        message="Status is required in request body.",
                        status=status_code.phrase,
                    ),
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
                return (
                    jsonify(
                        message=f"Invalid status. Must be one of: {', '.join(allowed_statuses)}",
                        status=status_code.phrase,
                    ),
                    status_code,
                )

            # TODO: Add authorization check - verify current user is recipient of friend request
            result = await self.conn.update_friend_relationship(connection_id, data)
            if result:  # Assuming update returns the updated connection or True
                # Send notification on acceptance/block?
                # if new_status == "accepted":
                #     await self.__notification_manager.send_friend_request_accepted_notification(...)
                status_code = HTTPStatus.OK
                return (
                    jsonify(
                        data=result,
                        message="Connection status updated successfully.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )
            else:
                app.logger.warning(
                    f"Failed to update connection {connection_id} (connector returned non-truthy)"
                )
                status_code = HTTPStatus.NOT_FOUND
                return (
                    jsonify(
                        message="Connection not found or update failed.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )

        except Exception as e:
            app.logger.error(
                f"Error updating connection {connection_id}: {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to update connection: {str(e)}",
                    status=status_code.phrase,
                ),
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
                return (
                    jsonify(
                        message="Connection deleted successfully.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )
            else:
                app.logger.warning(
                    f"Connection {connection_id} not found or deletion failed."
                )
                status_code = HTTPStatus.NOT_FOUND
                return (
                    jsonify(
                        message="Connection not found or could not be deleted.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )

        except Exception as e:
            app.logger.error(
                f"Error deleting connection {connection_id}: {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to delete connection: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

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
                return (
                    jsonify(
                        message="No file provided or file has no name.",
                        status=status_code.phrase,
                    ),
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
            return (
                jsonify(
                    data=response,
                    message="Media upload process initiated successfully.",
                    status=status_code.phrase,
                ),
                status_code,
            )  # 202 Accepted is suitable here

        except Exception as e:
            app.logger.error(
                f"Error initiating media upload for user {user_id}: {str(e)}",
                exc_info=True,
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to initiate media upload: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )
