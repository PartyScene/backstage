import httpx
import json

from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify
from quart.datastructures import FileStorage
from quart_jwt_extended import get_jwt_identity, jwt_required

from posts.src.connectors import PostsDB
from shared.utils import create_media_client, MediaClient
from shared.classful import route, QuartClassful
from http import HTTPStatus
import os
from datetime import datetime
from aiocache import cached


class BaseView(QuartClassful):

    def __init__(self) -> None:
        self.__media_client: MediaClient = create_media_client(
            os.environ["MEDIA_MICROSERVICE_URL"]
        )
        self.__posts_handler: PostsDB = app.conn

        self.redis = app.redis

    @route("/", methods=["GET"])
    async def index(self):
        return await self.healthcheck()
        
    @route("/posts/health", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def healthcheck(self):
        """
        Simple health check endpoint that verifies service and dependency status.
        Returns 200 OK if everything is healthy, 503 Service Unavailable otherwise.
        """
        health_status = {
            "service": "microservices.posts",
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "dependencies": {"database": "unknown", "redis": "unknown"},
        }

        # Check database connection
        try:
            db_info = await self.__posts_handler._info()
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

    @route("/posts/<post_id>/comments", methods=["GET"])
    @jwt_required
    async def get_comments(self, post_id):
        """
        Asynchronously gets all comments for a given post.
        Returns:
            Response: A JSON response containing a list of comments and a status code of 200 if successful.
                      If post ID is missing, returns a JSON error message and a status code of 400.
        """
        if result := await self.__posts_handler.fetch_comments(post_id):
            return jsonify(result), HTTPStatus.OK
        return (
            jsonify({"error": "No Comments found or Post not found"}),
            HTTPStatus.NOT_FOUND,
        )

    @route("/posts/<post_id>/comments", methods=["POST"])
    @jwt_required
    async def create_comment(self, post_id):
        """
        Asynchronously creates a new comment for a given post.
        Returns:
            Response: A JSON response containing the created comment and a status code of 201 if successful.
                      If post ID is missing, returns a JSON error message and a status code of 400.
        """
        data = await request.get_json()
        if not data:
            return jsonify({"error": "Content is required"}), HTTPStatus.BAD_REQUEST
        result = await self.__posts_handler.create_comment(
            post_id, data, get_jwt_identity()
        )
        if isinstance(result, str):
            return result, HTTPStatus.BAD_REQUEST
        return result, HTTPStatus.CREATED

    @route("/posts/<post_id>/comments/<comment_id>", methods=["DELETE"])
    @jwt_required
    async def delete_comment(self, post_id, comment_id):
        """
        Asynchronously deletes a comment for a given post.
        Returns:
            Response: A JSON response containing the created comment and a status code of 201 if successful.
                      If post ID is missing, returns a JSON error message and a status code of 400.
        """
        result = await self.__posts_handler.delete_comment(comment_id)
        app.logger.debug(json.dumps(result, indent=4, default=str))
        if isinstance(result, str):
            return result, HTTPStatus.BAD_REQUEST
        return result, HTTPStatus.NO_CONTENT

    @route("/posts/event/<id>", methods=["GET", "POST"])
    async def fetch_event_posts(self, id: str):
        """Fetch all posts for a given event"""
        return jsonify(await self.__posts_handler.fetch_event_posts(id), HTTPStatus.OK)

    @route("/posts", methods=["POST"])
    @jwt_required
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
        data = (await request.form).to_dict()
        content = data.get("content")

        if not content:
            return jsonify({"error": "Content is required"}), 400

        files = await request.files
        media_links = []

        for file_key in files:
            try:
                req = await self.__media_client.upload_media(request, files[file_key])
                media_links.append(req)
            except:
                return jsonify({"error": "Error uploading files"}), 400
        result = await self.__posts_handler.create_post(
            data=data, media_links=media_links, author=get_jwt_identity()
        )
        if isinstance(result, str):
            return result, HTTPStatus.BAD_REQUEST
        return result, HTTPStatus.CREATED

    @route("/posts/<id>", methods=["GET"])
    @jwt_required
    async def fetch_post(self, id: str):
        """
        Asynchronously gets a post with the provided ID.
        Returns:
            Response: A JSON response containing a success message and a status code of 200 if successful.
                      If ID is missing, returns a JSON error message and a status code of 400.
        """
        if result := await self.__posts_handler.fetch_post(id):
            return jsonify(result), HTTPStatus.OK
        return jsonify({"error": "Post not found"}), HTTPStatus.NOT_FOUND

    @route("/posts/<id>", methods=["DELETE"])
    @jwt_required
    async def delete_post(self, id: str):
        """
        Asynchronously deletes a post with the provided ID.
        This function handles the following:
        - Extracts form data from the request to get the ID of the post to be deleted.
        - Validates that the ID is provided.
        - Deletes the post with the given ID from the database.
        - Returns a success message as a JSON response.
        Returns:
            Response: A JSON response containing a success message and a status code of 200 if successful.
                      If ID is missing, returns a JSON error message and a status code of 400.
        """
        await self.__posts_handler.delete_post(id)
        return jsonify("Deleted"), HTTPStatus.NO_CONTENT
