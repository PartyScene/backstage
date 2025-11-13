import orjson as json
import asyncio
import os

from quart import current_app as app, request
from quart_jwt_extended import get_jwt_identity, jwt_required

from posts.src.connectors import PostsDB
from shared.classful import route, QuartClassful
from http import HTTPStatus
from datetime import datetime
from aiocache import cached

from shared.workers.rmq import RMQBroker
from shared.utils import recursively_sign_object_media, api_response, api_error
from shared.middleware.validation import ValidationMiddleware
import uuid_utils as ruuid

from surrealdb import RecordID


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

        return api_response(message, status_code, data=health_status)

    @route("/posts/<post_id>/report", methods=["POST"])
    @jwt_required
    async def report_post(self, post_id):
        """This endpoints reports a specific post"""
        reporter = get_jwt_identity()
        data = await request.get_json()
        reason = data.get("reason", "")
        if not reason:
            return api_error("Reason is required", HTTPStatus.BAD_REQUEST)

        # Check if the event exists

        post_info = await self.__posts_handler.fetch_post(post_id)
        if not post_info:
            return api_error("Post not found", HTTPStatus.NOT_FOUND)

        if result := await self.__posts_handler._report_resource(
            {"reason": reason, "reporter": reporter, "resource": post_info["id"]},
            "posts",
        ):
            return api_response(
                "Resource reported",
                HTTPStatus.CREATED,
                data=result,
            )

    @route("/posts/<post_id>/comments", methods=["GET"])
    @jwt_required
    async def get_comments(self, post_id):
        """
        Asynchronously gets all comments for a given post, excluding blocked users.
        """
        try:
            current_user_id = get_jwt_identity()
            if result := await self.__posts_handler.fetch_comments(post_id, current_user_id):
                return api_response(
                    "Comments fetched successfully.",
                    HTTPStatus.OK,
                    data=result,
                )
            return api_error(
                "No Comments found or Post not found",
                HTTPStatus.NOT_FOUND
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching comments for post {post_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to fetch comments: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
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
                return api_error("Content is required", HTTPStatus.BAD_REQUEST)

            result = await self.__posts_handler.create_comment(
                post_id, data, get_jwt_identity()
            )
            # Assuming the connector returns the created comment object on success
            # and raises an exception or returns None/False on failure.
            if result:  # Check if result is truthy (i.e., comment created)
                return api_response(
                    "Comment created successfully.",
                    HTTPStatus.CREATED,
                    data=result,
                )
            else:  # Handle cases where connector indicates failure without exception
                app.logger.warning(
                    f"Failed to create comment for post {post_id} (connector returned non-truthy)"
                )
                return api_error("Failed to create comment.", HTTPStatus.BAD_REQUEST)

        except (
            Exception
        ) as e:  # Catch potential exceptions from connector or request processing
            app.logger.error(
                f"Error creating comment for post {post_id}: {str(e)}", exc_info=True
            )
            # Provide a more specific error message if possible, e.g., based on exception type
            return api_error(
                f"Failed to create comment: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
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
                return api_response("Comment deleted successfully.", HTTPStatus.OK)
            else:
                # This might mean the comment didn't exist or deletion failed for other reasons
                app.logger.warning(
                    f"Comment {comment_id} not found or deletion failed."
                )
                return api_error(
                    "Comment not found or could not be deleted.",
                    HTTPStatus.NOT_FOUND
                )

        except Exception as e:
            app.logger.error(
                f"Error deleting comment {comment_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to delete comment: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/posts/<post_id>/comments/<comment_id>/report", methods=["POST"])
    @jwt_required
    async def report_comment(self, post_id, comment_id):
        """This endpoints reports a specific post"""
        reporter = get_jwt_identity()
        data = await request.get_json()
        reason = data.get("reason", "")
        if not reason:
            return api_error("Reason is required", HTTPStatus.BAD_REQUEST)

        # Check if the event exists

        comment_info = await self.__posts_handler.fetch_comment(comment_id)
        if not comment_info:
            return api_error("Comment not found", HTTPStatus.NOT_FOUND)

        if result := await self.__posts_handler._report_resource(
            {"reason": reason, "reporter": reporter, "resource": comment_info["id"]},
            "comments",
        ):
            return api_response(
                "Resource reported",
                HTTPStatus.CREATED,
                data=result,
            )

    @route("/posts/event/<id>", methods=["GET"])
    @jwt_required  # Added JWT requirement assuming it's needed
    async def fetch_event_posts(self, id: str):
        """Fetch all posts for a given event, excluding blocked users"""
        try:
            current_user_id = get_jwt_identity()
            result = await self.__posts_handler.fetch_event_posts(id, current_user_id)
            reuslt = await recursively_sign_object_media(result)
            return api_response(
                "Event posts fetched successfully.",
                HTTPStatus.OK,
                data=result,
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching posts for event {id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to fetch event posts: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/posts/user/<id>", methods=["GET"])
    @jwt_required  # Added JWT requirement assuming it's needed
    async def fetch_user_posts(self, id: str):
        """Fetch all posts for a user, excluding blocked users"""
        try:
            current_user_id = get_jwt_identity()
            result = await self.__posts_handler.fetch_user_posts(id, current_user_id)
            reuslt = await recursively_sign_object_media(result)
            return api_response(
                "User posts fetched successfully.",
                HTTPStatus.OK,
                data=result,
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching posts for user {id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to fetch user posts: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/posts", methods=["POST"])
    @ValidationMiddleware.validate_file_upload(
        max_size=50 * 1024 * 1024,  # 50MB for posts
        required=True
    )
    @jwt_required
    async def create_post(self):
        """
        Asynchronously creates a new post with the provided content, and optionally uploads media files.
        """
        try:
            form = await request.form
            files = await request.files
            data = form.to_dict()
            user_id = get_jwt_identity()
            content = data.get("content")



            if not content:
                return api_error("Content is required", HTTPStatus.BAD_REQUEST)

            # data["post_id"] = str(ruuid.uuid4()).split("-")[-1]
            data["coordinates"] = form.getlist("coordinates[]", type=float)
            data["post_id"] = (
                (RecordID("posts", str(ruuid.uuid4()).split("-")[-1]))
                if not data.get("id", None)
                else RecordID("posts", data["id"])
            )
            # Process filenames and detect MOV files for conversion
            processed_filenames = []
            processed_types = []
            
            for file in files.values():
                original_ext = os.path.splitext(file.filename)[-1].lower()
                # Convert MOV to MP4 for iOS compatibility
                if original_ext == '.mov' and file.content_type.startswith('video/'):
                    final_ext = '.mp4'
                    content_type = 'video/mp4'
                else:
                    final_ext = original_ext
                    content_type = file.content_type
                
                filename = f"posts/{user_id}/{data['post_id'].id}/{str(ruuid.uuid4()).split('-')[-1]}{final_ext}"
                processed_filenames.append(filename)
                processed_types.append(content_type)
                
            data["filenames"] = processed_filenames
            data["types"] = processed_types

            # CRITICAL: Validate post creation FIRST (before expensive media processing)
            result = await self.__posts_handler.create_post(data=data, author=user_id)

            if result:  # Post created successfully - now process media
                # Publish media upload tasks to RMQ (only after validation passes)
                media_publish_tasks = []
                for i, file in enumerate(files.values()):
                    if file.filename:  # Process only if file has a name
                        # Create isolated data dict for each file to prevent race conditions
                        file_data = {
                            "filename": data["filenames"][i],
                            "type": data["types"][i],
                            "creator": user_id,
                            "post_id": data["post_id"],
                        }
                        media_publish_tasks.append(app.RMQ._publish_media(file_data, file))

                if media_publish_tasks:
                    await asyncio.gather(*media_publish_tasks)  # Upload media concurrently
                
                # Return success response
                return api_response(
                    "Post created successfully, upload media to signed_urls.",
                    HTTPStatus.CREATED,
                    data=result,
                )
            else:
                app.logger.error(f"Failed to create post in DB for user {user_id}")
                # Attempt to clean up potentially uploaded media if post creation failed? (Complex)
                return api_error("Failed to create post.", HTTPStatus.INTERNAL_SERVER_ERROR)

        except Exception as e:
            app.logger.error(
                f"Error creating post for user {user_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to create post: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/posts/<id>", methods=["GET"])
    @jwt_required
    async def fetch_post(self, id: str):
        """
        Asynchronously gets a post with the provided ID.
        """
        try:
            if result := await self.__posts_handler.fetch_post(id):
                result = await recursively_sign_object_media(result)
                return api_response(
                    "Post fetched successfully.",
                    HTTPStatus.OK,
                    data=result,
                )
            return api_error("Post not found", HTTPStatus.NOT_FOUND)
        except Exception as e:
            app.logger.error(f"Error fetching post {id}: {str(e)}", exc_info=True)
            return api_error(
                f"Failed to fetch post: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
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
                return api_response("Post deleted successfully.", HTTPStatus.OK)
            else:
                app.logger.warning(f"Post {id} not found or deletion failed.")
                return api_error(
                    "Post not found or could not be deleted.",
                    HTTPStatus.NOT_FOUND
                )
        except Exception as e:
            app.logger.error(f"Error deleting post {id}: {str(e)}", exc_info=True)
            return api_error(
                f"Failed to delete post: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )