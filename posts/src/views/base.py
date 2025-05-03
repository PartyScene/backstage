import httpx
import orjson as json
import uuid
import asyncio

from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify
from quart.datastructures import FileStorage
from quart_jwt_extended import get_jwt_identity, jwt_required

from posts.src.connectors import PostsDB
from shared.classful import route, QuartClassful
from http import HTTPStatus
import os
from datetime import datetime
from aiocache import cached

from shared.workers.rmq import RMQBroker
import uuid_utils as ruuid


class BaseView(QuartClassful):

    def __init__(self) -> None:
        self.__posts_handler: PostsDB = app.conn
        self.redis = app.redis

    @route("/", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
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
        message = "Service is healthy"
        status_code = HTTPStatus.OK

        # Check database connection
        try:
            db_info = await self.__posts_handler._info()
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

    @route("/posts/<post_id>/comments", methods=["GET"])
    @jwt_required
    async def get_comments(self, post_id):
        """
        Asynchronously gets all comments for a given post.
        """
        try:
            if result := await self.__posts_handler.fetch_comments(post_id):
                status_code = HTTPStatus.OK
                return (
                    jsonify(
                        data=result,
                        message="Comments fetched successfully.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )
            status_code = HTTPStatus.NOT_FOUND
            return (
                jsonify(
                    message="No Comments found or Post not found",
                    status=status_code.phrase,
                ),
                status_code,
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching comments for post {post_id}: {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to fetch comments: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/posts/<post_id>/comments", methods=["POST"])
    @jwt_required
    async def create_comment(self, post_id):
        """
        Asynchronously creates a new comment for a given post.
        """
        try:
            data = await request.get_json()
            if not data or not data.get(
                "content"
            ):  # Check if data exists and has content
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(message="Content is required", status=status_code.phrase),
                    status_code,
                )

            result = await self.__posts_handler.create_comment(
                post_id, data, get_jwt_identity()
            )
            # Assuming the connector returns the created comment object on success
            # and raises an exception or returns None/False on failure.
            if result:  # Check if result is truthy (i.e., comment created)
                status_code = HTTPStatus.CREATED
                return (
                    jsonify(
                        data=result,
                        message="Comment created successfully.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )
            else:  # Handle cases where connector indicates failure without exception
                app.logger.warning(
                    f"Failed to create comment for post {post_id} (connector returned non-truthy)"
                )
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="Failed to create comment.", status=status_code.phrase
                    ),
                    status_code,
                )

        except (
            Exception
        ) as e:  # Catch potential exceptions from connector or request processing
            app.logger.error(
                f"Error creating comment for post {post_id}: {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            # Provide a more specific error message if possible, e.g., based on exception type
            return (
                jsonify(
                    message=f"Failed to create comment: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/posts/<post_id>/comments/<comment_id>", methods=["DELETE"])
    @jwt_required
    async def delete_comment(self, post_id, comment_id):
        """
        Asynchronously deletes a comment for a given post.
        """
        try:
            # Optional: Add check if the user is authorized to delete this comment
            user_id = get_jwt_identity()
            # comment = await self.__posts_handler.fetch_comment(comment_id) # Need a fetch_comment method
            # if not comment:
            #     status_code = HTTPStatus.NOT_FOUND
            #     return jsonify(message="Comment not found", status=status_code.phrase), status_code
            # if comment.get("author") != user_id:
            #     status_code = HTTPStatus.FORBIDDEN
            #     return jsonify(message="Unauthorized to delete this comment", status=status_code.phrase), status_code

            result = await self.__posts_handler.delete_comment(comment_id)
            app.logger.debug(
                f"Delete comment result for {comment_id}: {result}"
            )  # Log result for debugging

            # Check if deletion was successful (connector might return boolean or affected count)
            if (
                result
            ):  # Adjust condition based on what delete_comment returns on success
                status_code = HTTPStatus.NO_CONTENT
                return (
                    jsonify(
                        message="Comment deleted successfully.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )
            else:
                # This might mean the comment didn't exist or deletion failed for other reasons
                app.logger.warning(
                    f"Comment {comment_id} not found or deletion failed."
                )
                status_code = HTTPStatus.NOT_FOUND
                return (
                    jsonify(
                        message="Comment not found or could not be deleted.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )

        except Exception as e:
            app.logger.error(
                f"Error deleting comment {comment_id}: {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to delete comment: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/posts/<post_id>/comments/<comment_id>/report", methods=["POST"])
    @jwt_required
    async def report_comment(self, post_id, comment_id):
        """This endpoints reports a specific post"""
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

        comment_info = await self.__posts_handler.fetch_comment(comment_id)
        if not comment_info:
            status_code = HTTPStatus.NOT_FOUND
            return (
                jsonify(message="Comment not found", status=status_code.phrase),
                status_code,
            )

        if result := await self.__posts_handler._report_resource(
            {"reason": reason, "reporter": reporter, "resource": comment_info["id"]},
            "comments",
        ):
            status_code = HTTPStatus.CREATED
            return (
                jsonify(
                    message="Resource reported", data=result, status=status_code.phrase
                ),
                status_code,
            )

    @route("/posts/event/<id>", methods=["GET"])
    @jwt_required  # Added JWT requirement assuming it's needed
    async def fetch_event_posts(self, id: str):
        """Fetch all posts for a given event"""
        try:
            result = await self.__posts_handler.fetch_event_posts(id)
            status_code = HTTPStatus.OK
            return (
                jsonify(
                    data=result,
                    message="Event posts fetched successfully.",
                    status=status_code.phrase,
                ),
                status_code,
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching posts for event {id}: {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to fetch event posts: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/posts", methods=["POST"])
    @jwt_required
    async def create_post(self):
        """
        Asynchronously creates a new post with the provided content, and optionally uploads media files.
        """
        try:
            data = (await request.form).to_dict()
            files = await request.files
            user_id = get_jwt_identity()
            content = data.get("content")

            if not content:
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(message="Content is required", status=status_code.phrase),
                    status_code,
                )

            data["post_id"] = str(ruuid.uuid4()).split("-")[-1]
            data["filenames"] = [
                f"posts/{user_id}/{data['post_id']}/{str(ruuid.uuid4()).split('-')[-1]}{os.path.splitext(file.filename)[-1]}"
                for file in files.values()
                if file.filename  # Ensure file has a name
            ]
            data["types"] = [
                file.content_type for file in files.values() if file.filename
            ]

            # Publish media upload tasks to RMQ
            media_publish_tasks = []
            for i, file in enumerate(files.values()):
                if file.filename:  # Process only if file has a name
                    media_data = (
                        data.copy()
                    )  # Avoid modifying original data dict in loop
                    media_data["filename"] = data["filenames"][i]
                    media_data["type"] = data["types"][i]
                    media_publish_tasks.append(app.RMQ._publish_media(media_data, file))

            if media_publish_tasks:
                await asyncio.gather(*media_publish_tasks)  # Upload media concurrently

            # Create post in the database
            result = await self.__posts_handler.create_post(data=data, author=user_id)

            if result:  # Assuming create_post returns the created post object
                status_code = HTTPStatus.CREATED
                return (
                    jsonify(
                        data=result,
                        message="Post created successfully.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )
            else:
                app.logger.error(f"Failed to create post in DB for user {user_id}")
                # Attempt to clean up potentially uploaded media if post creation failed? (Complex)
                status_code = HTTPStatus.INTERNAL_SERVER_ERROR
                return (
                    jsonify(
                        message="Failed to create post.", status=status_code.phrase
                    ),
                    status_code,
                )

        except Exception as e:
            app.logger.error(
                f"Error creating post for user {user_id}: {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to create post: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/posts/<id>", methods=["GET"])
    @jwt_required
    async def fetch_post(self, id: str):
        """
        Asynchronously gets a post with the provided ID.
        """
        try:
            if result := await self.__posts_handler.fetch_post(id):
                status_code = HTTPStatus.OK
                return (
                    jsonify(
                        data=result,
                        message="Post fetched successfully.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )
            status_code = HTTPStatus.NOT_FOUND
            return (
                jsonify(message="Post not found", status=status_code.phrase),
                status_code,
            )
        except Exception as e:
            app.logger.error(f"Error fetching post {id}: {str(e)}", exc_info=True)
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to fetch post: {str(e)}", status=status_code.phrase
                ),
                status_code,
            )

    @route("/posts/<id>", methods=["DELETE"])
    @jwt_required
    async def delete_post(self, id: str):
        """
        Asynchronously deletes a post with the provided ID.
        """
        try:
            # Optional: Add check if the user is authorized to delete this post
            user_id = get_jwt_identity()
            # post = await self.__posts_handler.fetch_post(id)
            # if not post:
            #     status_code = HTTPStatus.NOT_FOUND
            #     return jsonify(message="Post not found", status=status_code.phrase), status_code
            # if post.get("author") != user_id: # Assuming author field stores user ID
            #     status_code = HTTPStatus.FORBIDDEN
            #     return jsonify(message="Unauthorized to delete this post", status=status_code.phrase), status_code

            result = await self.__posts_handler.delete_post(id)
            # Check if deletion was successful (adjust based on connector's return value)
            if result:
                # Consider deleting associated media from storage here or via another mechanism
                status_code = HTTPStatus.NO_CONTENT
                return (
                    jsonify(
                        message="Post deleted successfully.", status=status_code.phrase
                    ),
                    status_code,
                )
            else:
                app.logger.warning(f"Post {id} not found or deletion failed.")
                status_code = HTTPStatus.NOT_FOUND
                return (
                    jsonify(
                        message="Post not found or could not be deleted.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )
        except Exception as e:
            app.logger.error(f"Error deleting post {id}: {str(e)}", exc_info=True)
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to delete post: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/posts/<post_id>/report", methods=["POST"])
    @jwt_required
    async def report_post(self, post_id):
        """This endpoints reports a specific post"""
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

        post_info = await self.__posts_handler.fetch_post(post_id)
        if not post_info:
            status_code = HTTPStatus.NOT_FOUND
            return (
                jsonify(message="Post not found", status=status_code.phrase),
                status_code,
            )

        if result := await self.__posts_handler._report_resource(
            {"reason": reason, "reporter": reporter, "resource": post_info["id"]}, "posts"
        ):
            status_code = HTTPStatus.CREATED
            return (
                jsonify(
                    message="Resource reported", data=result, status=status_code.phrase
                ),
                status_code,
            )
