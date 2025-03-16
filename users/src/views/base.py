import httpx
from quart import request, current_app as app, jsonify
from quart_jwt_extended import get_jwt_identity, jwt_required
from http import HTTPStatus
from typing import Tuple, Dict, Any

from shared.classful import route, QuartClassful
from datetime import datetime
from shared.utils import create_media_client

from users.src.connectors import UsersDB
from shared.notifications import NotificationManager
import logging
import json
import os

logger = logging.getLogger(__name__)


class BaseView(QuartClassful):
    def __init__(self):
        self.conn: UsersDB = app.conn
        self.redis = app.redis
        self.__media_client = create_media_client(os.environ["MEDIA_MICROSERVICE_URL"])
        self.__notification_manager = NotificationManager()
    
    
    @route("/", methods=["GET"])
    async def index(self):
        return await self.healthcheck()

    @route("/users/health", methods=["GET"])
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

        # Check database connection
        try:
            db_info = await self.conn.db.info()
            health_status["dependencies"]["database"] = "healthy"
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
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
            logger.error(f"Redis health check failed: {e}")
            health_status["dependencies"]["redis"] = "unhealthy"
            health_status["status"] = "degraded"

        status_code = (
            HTTPStatus.OK
            if health_status["status"] == "healthy"
            else HTTPStatus.SERVICE_UNAVAILABLE
        )

        return jsonify(health_status), status_code

    @route("/user", methods=["GET"])
    @jwt_required
    async def get_me(self) -> Tuple[Dict[str, Any], int]:
        """Get current user details including friend connections and attended events"""
        try:
            user_id = get_jwt_identity()
            user = await self.conn.fetch(user_id)
            if not user:
                return {"error": "User not found"}, HTTPStatus.NOT_FOUND
            return user, HTTPStatus.OK
        except Exception as e:
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/user", methods=["DELETE"])
    @jwt_required
    async def delete_me(self) -> Tuple[Dict[str, Any], int]:
        """Delete current user and their relationships"""
        try:
            user_id = get_jwt_identity()
            result = await self.conn.delete(user_id)
            if not result:
                return {"error": "User not found"}, HTTPStatus.NOT_FOUND
            return {"message": "User deleted successfully"}, HTTPStatus.NO_CONTENT
        except Exception as e:
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/user", methods=["PATCH"])
    @jwt_required
    async def update_me(self) -> Tuple[Dict[str, Any], int]:
        """Update current user information"""
        try:
            user_id = get_jwt_identity()
            data = await request.get_json()
            data["id"] = user_id
            result = await self.conn.update(data)
            return result, HTTPStatus.OK
        except Exception as e:
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    # @route("/friends", methods=["GET"])
    # @jwt_required
    # async def get_friends(self) -> Tuple[Dict[str, Any], int]:
    #     """Get user's friends with specified degree of separation"""
    #     try:
    #         user_id = get_jwt_identity()
    #         degree = request.args.get('degree', type=int, default=1)
    #         target_id = request.args.get('target')

    #         data = {"origin": user_id}
    #         if target_id:
    #             data["target"] = target_id

    #         result = await self.conn.find_friend_relationship(data, degree)
    #         return {"friends": result}, HTTPStatus.OK
    #     except Exception as e:
    #         return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/users/<user_id>", methods=["GET"])
    @jwt_required
    async def get_user(self, user_id: str) -> Tuple[Dict[str, Any], int]:
        """Get another user's public profile"""
        try:
            user = await self.conn.fetch(user_id)
            if not user:
                return {"error": "User not found"}, HTTPStatus.NOT_FOUND
            # Could filter sensitive information here if needed
            return user, HTTPStatus.OK
        except Exception as e:
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/friends", methods=["GET"])
    @jwt_required
    async def get_connections_at_degree(self) -> Tuple[Dict[str, Any], int]:
        """
        Get all connections up to N degrees of separation

        Query Parameters:
            max_degree (int): Maximum degree of separation (1-6, default: 3)
        """
        try:
            user_id = get_jwt_identity()
            max_degree = request.args.get("max_degree", type=int, default=1)

            if max_degree < 1 or max_degree > 6:
                return {
                    "error": "max_degree must be between 1 and 6"
                }, HTTPStatus.BAD_REQUEST

            result = await self.conn.find_connections_at_degree(user_id, max_degree)
            return jsonify(result), HTTPStatus.OK
        except Exception as e:
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/friends", methods=["POST"])
    @jwt_required
    async def create_connection(self) -> Tuple[Dict[str, Any], int]:
        """Create a friendship connection with another user"""
        data: dict = await request.get_json()
        data["origin_id"] = get_jwt_identity()
        if result := await self.conn.create_friend_relationship(data):
            logger.info(json.dumps(result, indent=4, default=str))
            await self.__notification_manager.send_friend_request_notification(
                sender=result[0]["in"], recipient_id=result[0]["out"]
            )
            return result, HTTPStatus.CREATED
        return {
            "error": "Failed to create connection"
        }, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/friends/<connection_id>", methods=["PATCH"])
    @jwt_required
    async def update_connection(self, connection_id: str) -> Tuple[Dict[str, Any], int]:
        """
        Update the connection status between two users

        Query Parameters:
            connection_id (str): The ID of the target relationship
            status (str): The new connection status (either "pending", "accepted", or "blocked")
        """
        data: dict = await request.get_json()

        if "status" not in data:
            return {"error": "Status is required"}, HTTPStatus.BAD_REQUEST

        result = await self.conn.update_friend_relationship(connection_id, data)
        return result, HTTPStatus.OK

    @route("/friends/<connection_id>", methods=["DELETE"])
    @jwt_required
    async def delete_connection(self, connection_id: str) -> Tuple[Dict[str, Any], int]:
        """Delete a friendship connection with another user"""
        result = await self.conn.delete_connection(connection_id)
        return result, HTTPStatus.NO_CONTENT

    @route("/users/upload", methods=["POST"])
    @jwt_required
    async def upload_media(self):
        """
        Uploads a file to the Media Microservice and updates the user's avatar URL.

        Request Body:
            file (file): The file to upload

        Returns:
            dict: Updated user data
        """
        try:
            user_id = get_jwt_identity()
            data = {"id": user_id}  # Changed from 'user' to 'id' to match update method

            file = (await request.files).get("file")
            if not file:
                return {"error": "No file provided"}, HTTPStatus.BAD_REQUEST

            # Relay file to the Media Microservice
            media_data = await self.__media_client.upload_media(request, file)
            media_link = media_data.get("url")
            if not media_link:
                return {
                    "error": "Invalid response from Media Microservice"
                }, HTTPStatus.BAD_GATEWAY

            data["avatar_url"] = media_link
            response = await self.conn.update(data)
            return response, HTTPStatus.OK
        except Exception as e:
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    async def create_friend_request(self, sender_id: str, recipient_id: str):
        """
        Send a friend request notification
        """
        try:
            # Assuming create_friend_relationship is an existing method in Users connector
            friend_request = await self.conn.create_friend_relationship(
                {"origin": sender_id, "target": recipient_id, "status": "pending"}
            )

            # Send notification to the recipient
            self.__notification_manager.send_friend_request_notification(
                sender_id=sender_id, recipient_id=recipient_id
            )

            return friend_request
        except Exception as e:
            # Log the error and handle appropriately
            logger.error(f"Friend request error: {e}")
            raise
