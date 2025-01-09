import httpx
from quart import current_app as app, request, jsonify
from quart.datastructures import FileStorage
from quart_jwt_extended import get_jwt_identity, jwt_required

from ..connectors import UsersDB

from classful import route, QuartClassful


class BaseView(QuartClassful):

    def __init__(self):
        self.MEDIA_MICROSERVICE_URL = 'http://microservices.media:5510/upload'
        self.db: UsersDB = app.db

    @route("/users/", methods=["GET", "POST", "DELETE"])
    @jwt_required
    async def index(self):
        """Fetch a USER profile"""
        ...
        data = await request.get_json()
        match request.method:
            case "POST":
                response = await self.db.users.fetch(data["email"])
            case "DELETE":
                response = await self.db.users.delete(data["email"])

        return response, 200
    
    
    @route("/relationships/create", methods=["POST"])
    @jwt_required
    async def create_relationship(self):
        """Create a Friend Relationship in the Database with the logged in user."""
        data = await request.get_json()
        data['origin'] = get_jwt_identity()
        response = await self.db.users.create_friend_relationship(data)
        return response, 201
    
    @route("/relationships/find", methods=["GET"])
    @jwt_required
    async def find_relationship(self):
        """Find a Friend Relationship in the Database with the logged in user."""
        data = await request.get_json() # data is structured as {'degree': 1}
        data['origin'] = get_jwt_identity()
        response = await self.db.users.find_friend_relationship(data, degree = data['degree'])
        return response, 200
    
    @route("/users/upload", methods=["POST"])
    @jwt_required
    async def upload_media(self):
        """This endpoint is the primary upload endpoint - TODO: handle multiple media types

        Returns:
            _type_: _description_
        """
        data = {
            'user' : get_jwt_identity()
        }
        
        # check if there is an upload.
        file = (await request.files).get('file')
        if file:
                # Relay file to the Media Microservice
            async with httpx.AsyncClient() as client:
                try:
                    media_response = await client.post(
                        self.MEDIA_MICROSERVICE_URL,
                        files={"file": (file.filename, file.stream, file.content_type)},
                        headers = request.headers
                    )
                    media_response.raise_for_status()
                except httpx.HTTPError as e:
                    return jsonify({"error": f"Media upload failed: {str(e)}"}), 500

            # Extract media URL from the Media Microservice response
            media_data = media_response.json()
            media_link = media_data.get('url')
            if not media_link:
                return jsonify({"error": "Invalid response from Media Microservice"}), 500
            
            data['avatar_url'] = media_link # Set the media link to the database field we have currently
        response = await self.db.users.update(data)
        return response, 200

    @route("/me", methods=["GET", "POST", "PUT", "PATCH"])
    @jwt_required
    async def me(self):
        """Endpoint for the currently authenticated user"""
        match request.method:
            case "PATCH":
                data = await request.get_json()
                response = await self.db.users.update(data)
            case "POST":
                response = await self.db.users.fetch(get_jwt_identity())
        return response, 200