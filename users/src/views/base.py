import httpx
from quart import request, current_app as app
from quart_jwt_extended import get_jwt_identity, jwt_required
from http import HTTPStatus
from typing import Tuple, Dict, Any

from classful import route, QuartClassful
from ..connectors import UsersDB


class BaseView(QuartClassful):
    def __init__(self):
        self.MEDIA_MICROSERVICE_URL = 'http://microservices.media:5510/upload'
        self.db: UsersDB = app.db

    @route("/user", methods=["GET"])
    @jwt_required
    async def get_me(self) -> Tuple[Dict[str, Any], int]:
        """Get current user details including friend connections and attended events"""
        try:
            user_id = get_jwt_identity()
            user = await self.db.users.fetch(user_id)
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
            result = await self.db.users.delete(user_id)
            if not result:
                return {"error": "User not found"}, HTTPStatus.NOT_FOUND
            return {"message": "User deleted successfully"}, HTTPStatus.OK
        except Exception as e:
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/user", methods=["PATCH"])
    @jwt_required
    async def update_me(self) -> Tuple[Dict[str, Any], int]:
        """Update current user information"""
        try:
            user_id = get_jwt_identity()
            data = await request.get_json()
            data['id'] = user_id
            result = await self.db.users.update(data)
            return result, HTTPStatus.OK
        except Exception as e:
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/friends", methods=["GET"])
    @jwt_required
    async def get_friends(self) -> Tuple[Dict[str, Any], int]:
        """Get user's friends with specified degree of separation"""
        try:
            user_id = get_jwt_identity()
            degree = request.args.get('degree', type=int, default=1)
            target_id = request.args.get('target')
            
            data = {"origin": user_id}
            if target_id:
                data["target"] = target_id
                
            result = await self.db.users.find_friend_relationship(data, degree)
            return {"friends": result}, HTTPStatus.OK
        except Exception as e:
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/users/<user_id>", methods=["GET"])
    @jwt_required
    async def get_user(self, user_id: str) -> Tuple[Dict[str, Any], int]:
        """Get another user's public profile"""
        try:
            user = await self.db.users.fetch(user_id)
            if not user:
                return {"error": "User not found"}, HTTPStatus.NOT_FOUND
            # Could filter sensitive information here if needed
            return user, HTTPStatus.OK
        except Exception as e:
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/friends/connections", methods=["GET"])
    @jwt_required
    async def get_connections_at_degree(self) -> Tuple[Dict[str, Any], int]:
        """
        Get all connections up to N degrees of separation
        
        Query Parameters:
            max_degree (int): Maximum degree of separation (1-6, default: 3)
        """
        try:
            user_id = get_jwt_identity()
            max_degree = request.args.get('max_degree', type=int, default=3)
            
            if max_degree < 1 or max_degree > 6:
                return {"error": "max_degree must be between 1 and 6"}, HTTPStatus.BAD_REQUEST
                
            result = await self.db.users.find_connections_at_degree(user_id, max_degree)
            return {"connections": result}, HTTPStatus.OK
        except Exception as e:
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/friends", methods=["POST"])
    @jwt_required
    async def create_friendship(self) -> Tuple[Dict[str, Any], int]:
        """Create a friendship connection with another user"""
        try:
            user_id = get_jwt_identity()
            data = await request.get_json()
            data['origin'] = user_id
            
            if 'target' not in data:
                return {"error": "Target user ID is required"}, HTTPStatus.BAD_REQUEST
                
            result = await self.db.users.create_friend_relationship(data)
            return result, HTTPStatus.CREATED
        except Exception as e:
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/upload", methods=["POST"])
    @jwt_required
    async def upload_media(self):
        """Upload user media (avatar, etc.)"""
        try:
            user_id = get_jwt_identity()
            data = {'id': user_id}  # Changed from 'user' to 'id' to match update method
            
            file = (await request.files).get('file')
            if not file:
                return {"error": "No file provided"}, HTTPStatus.BAD_REQUEST

            # Relay file to the Media Microservice
            async with httpx.AsyncClient() as client:
                try:
                    media_response = await client.post(
                        self.MEDIA_MICROSERVICE_URL,
                        files={"file": (file.filename, file.stream, file.content_type)},
                        headers=request.headers
                    )
                    media_response.raise_for_status()
                except httpx.HTTPError as e:
                    return {"error": f"Media upload failed: {str(e)}"}, HTTPStatus.BAD_GATEWAY

                # Extract media URL from the Media Microservice response
                media_data = media_response.json()
                media_link = media_data.get('url')
                if not media_link:
                    return {"error": "Invalid response from Media Microservice"}, HTTPStatus.BAD_GATEWAY
                
                data['avatar_url'] = media_link
                response = await self.db.users.update(data)
                return response, HTTPStatus.OK
        except Exception as e:
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR