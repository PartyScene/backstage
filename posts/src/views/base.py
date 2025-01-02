
import httpx

from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify
from quart.datastructures import FileStorage
from quart_jwt_extended import get_jwt_identity, jwt_required

from ..connectors import PostsDB
from classful import route, QuartClassful


class BaseView(QuartClassful):
    app = app
    route_base = "/posts/"
    MEDIA_MICROSERVICE_URL = 'http://microservices.media:5510/upload'

    @route("/<id>", methods=["GET", "POST"])
    async def index(self, id: str):
        """Fetch a POST"""
        ...
    
    @route("/", methods=["POST"])
    @jwt_required()
    async def create_post(self):
        """
        Asynchronously creates a new post with the provided content, and optionally uploads media files.
        This function handles the following:
        - Extracts form data from the request to get the title and content of the post.
        - Validates that both title and content are provided.
        - Generates a unique post ID and constructs a post dictionary with the provided data.
        - Optionally uploads media files to a media microservice and includes the media links in the post.
        - Returns the created post as a JSON response.
        Returns:
            Response: A JSON response containing the created post and a status code of 201 if successful.
                      If title or content is missing, returns a JSON error message and a status code of 400.
                      If media upload fails, returns a JSON error message and a status code of 500.
        """
        """"""
        data = await request.get_json()
        content = data.get('content')

        if not content:
            return jsonify({"error": "Content is required"}), 400
        
        files = request.files
        media_links = []

        for file_key in files:
            file: FileStorage = files[file_key]
            if file:
            # Send the file to the media microservice
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
                    if not media_data:
                        return jsonify({"error": "Invalid response from Media Microservice"}), 500
                media_links.append(media_data.get('url'))
                
        await self.app.db.create_post(content=data['content'], media_links=media_links, author = get_jwt_identity())
        return jsonify("Created"), 201