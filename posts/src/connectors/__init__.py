from quart import Quart
import os
import datetime
import orjson as json

from surrealdb import AsyncSurreal, RecordID
from typing import Literal
from shared.utils import record_id_to_json, report_resource
import shared.utils
from purreal import SurrealDBConnectionPool, SurrealDBPoolManager


class PostsDB:
    def __init__(self, pool: SurrealDBConnectionPool, logger) -> None:
        self.pool = pool
        self.logger = logger

    async def _report_resource(
        self, data: dict, resource: Literal["posts", "comments"]
    ) -> dict:
        """
        Report this resource which is either a post or a comment

        Args:
            data (dict): The data to report
            resource: Table name - either "posts" or "comments"
        """
        return await report_resource(self.pool, data, resource_table=resource)

    async def _info(self):
        """Get database information."""
        return await self.pool.execute_query("INFO FOR DB")

    async def fetch_event_posts(self, id: str, current_user_id: str = None) -> dict:
        """
        Asynchronously fetches all posts associated with the given event.
        Filters out posts from users with blocking relationships.
            Args:
                id (str): The ID of the event.
                current_user_id (str): The ID of the current user (for blocking filter).
            Returns:
                dict: A dictionary containing the result of the post fetch query.
        """
        event_rid = RecordID("events", id)
        
        if current_user_id:
            # Filter out posts where blocking relationship exists
            current_user_rid = RecordID("users", current_user_id)
            query = """
                    SELECT fn::fetch_post(id) AS post 
                    FROM posts 
                    WHERE event == $event_id
                    AND (SELECT VALUE <->(blocks WHERE $parent.in IN [in, out])
                            FROM $current_user_id)[0] == [];
                """
            params = {"event_id": event_rid, "current_user_id": current_user_rid}
        else:
            # No blocking filter if user is not authenticated
            query = """
                    SELECT fn::fetch_post(id) AS post FROM posts WHERE event == $event_id;
                """
            params = {"event_id": event_rid}
        
        async with self.pool.acquire() as conn:
            result = await conn.query(query, params)
        self.logger.info(json.dumps(result, option=json.OPT_INDENT_2, default=str))
        return record_id_to_json(result)

    async def fetch_user_posts(self, id: str, current_user_id: str = None) -> dict:
        """
        Asynchronously fetches all posts associated with the given user.
        Filters out posts from users with blocking relationships.
            Args:
                id (str): The ID of the user whose posts to fetch.
                current_user_id (str): The ID of the current user (for blocking filter).
            Returns:
                dict: A dictionary containing the result of the post fetch query.
        """
        user_rid = RecordID("users", id)
        
        if current_user_id:
            # Filter out posts where blocking relationship exists
            current_user_rid = RecordID("users", current_user_id)
            query = """
                    SELECT fn::fetch_post(id) AS post 
                    FROM posts 
                    WHERE in == $user_id
                    AND (SELECT VALUE <->(blocks WHERE $parent.in IN [in, out])
                            FROM $current_user_id)[0] == [];
                """
            params = {"user_id": user_rid, "current_user_id": current_user_rid}
        else:
            # No blocking filter if user is not authenticated
            query = """
                    SELECT fn::fetch_post(id) AS post FROM posts WHERE in == $user_id;
                """
            params = {"user_id": user_rid}
        
        async with self.pool.acquire() as conn:
            result = await conn.query(query, params)
        self.logger.info(json.dumps(result, option=json.OPT_INDENT_2, default=str))
        return record_id_to_json(result)

    async def create_comment(self, post_id, data, author) -> dict:
        """
        Asynchronously creates a new comment in the database.
            Args:
                post_id (str): The ID of the post.
                data (dict): A dictionary containing the comment data.
                author (str): The ID of the author creating the comment.
            Returns:
                dict: A dictionary containing the result of the comment creation query.
        """
        async with self.pool.acquire() as conn:
            await conn.let("user", RecordID("users", author))
            await conn.let("post", RecordID("posts", post_id))
            query = """
            RELATE ONLY $user -> comments -> $post SET content = $content;
            """
            params = {"content": data["content"]}
            result = await conn.query(query, params)
        return record_id_to_json(result)

    async def fetch_comments(self, post_id: str, current_user_id: str = None) -> dict:
        """
        Asynchronously fetches all comments associated with the given post.
        Filters out comments from users with blocking relationships.
            Args:
                post_id (str): The ID of the post.
                current_user_id (str): The ID of the current user (for blocking filter).
            Returns:
                dict: A dictionary containing the result of the comment fetch query.
        """
        post = RecordID("posts", post_id)
        
        if current_user_id:
            # Filter out comments where blocking relationship exists
            current_user_rid = RecordID("users", current_user_id)
            query = """
                    SELECT VALUE [
                        FOR $comment IN (<-comments.* AS comments)
                        WHERE (SELECT VALUE <->(blocks WHERE $parent.in IN [in, out])
                            FROM $current_user_id)[0] == []
                    ] FROM ONLY $post
                """
            params = {"post": post, "current_user_id": current_user_rid}
        else:
            # No blocking filter if user is not authenticated
            query = """SELECT <-comments.* AS comments FROM ONLY $post"""
            params = {"post": post}
        
        async with self.pool.acquire() as conn:
            result = await conn.query(query, params)
        return record_id_to_json(result)

    async def delete_comment(self, comment_id):
        """
        Asynchronously deletes a post associated with the given data.
        Args:
            data (dict): post data to be deleted, must include SurrealDB ID.
        Returns:
            dict: The result of the deletion operation.
        Raises:
            Exception: If the deletion operation fails.
        """
        async with self.pool.acquire() as conn:
            result = await conn.delete(RecordID("comments", comment_id))
        return record_id_to_json(result)

    async def fetch_comment(self, comment_id):
        """
        Asynchronously fetches a comment associated with the given ID.
            Args:
                id (str): ID of the comment to be fetched.
            Returns:
                dict: The result of the fetch operation.
            Raises:
                Exception: If the deletion operation fails.
        """
        async with self.pool.acquire() as conn:
            result = await conn.select(RecordID("comments", comment_id))
        self.logger.debug(json.dumps(result, option=json.OPT_INDENT_2, default=str))
        return record_id_to_json(result)

    async def user_has_ticket(self, user_id, event_id) -> bool:
        """
        Asynchronously checks if a user has a ticket for a given event.
            Args:
                user_id (str): The ID of the user.
                event_id (str): The ID of the event.
            Returns:
                bool: True if the user has a ticket for the event, False otherwise.
        """
        async with self.pool.acquire() as conn:
            result = await conn.query("SELECT * FROM tickets WHERE user = $user AND event = $event", {"user": user_id, "event": event_id})
        return len(result) > 0

    async def create_post(self, data, author) -> dict:
        """
        Asynchronously creates a new post in the database.
            Args:
                data (dict): A dictionary containing the post data.
                media_links (list): A list of media links associated with the post.
                author (str): The ID of the author creating the post.
            Returns:
                dict: A dictionary containing the result of the post creation query.
        """
        async with self.pool.acquire() as conn:
            await conn.let("users", RecordID("users", author))
            media_query_result = {"id": None}  # Initialize media_query_result
            if "event" not in data:
                raise ValueError("Event ID is required to create a post.")
            if "content" not in data:
                raise ValueError("Content is required to create a post.")

            data["creator"] = RecordID("users", author)
            data["event"] = RecordID("events", data["event"])

            
            event_info = await conn.select(data["event"])
            
            # Check if user is the event creator/host - they don't need tickets
            is_event_host = event_info[0].get("host") == data["creator"]
            
            # Only check for ticket if user is not the event host
            if not is_event_host:
                if not await self.user_has_ticket(data["creator"], data["event"]):
                    raise ValueError("User does not have a ticket for this event.")

            # Check if post is close to event location
            if "coordinates" in data and "location" in event_info:
                event_coordinates = event_info["location"]["coordinates"]
                post_coordinates = data["coordinates"]
                post_coordinates = shared.utils.coordinates_to_geometry_point(post_coordinates)
                if not event_coordinates or not post_coordinates:
                    raise ValueError(
                        "Coordinates are required for both event and post."
                    )

                distance_result = await conn.query(
                    "RETURN geo::distance($post_location, $event_location);",
                    {
                        "post_location": post_coordinates,
                        "event_location": event_coordinates,
                    },
                )
                distance_meters = float(distance_result) if distance_result else float('inf')
                
                # Allow posts within 1km of event (adjust for large venues/festivals)
                MAX_DISTANCE_METERS = 1000
                if distance_meters > MAX_DISTANCE_METERS:
                    raise ValueError(
                        f"Post location is {distance_meters:.0f}m from event location (maximum: {MAX_DISTANCE_METERS}m)."
                    )

            # Check event timing: only allow posts if event starts within 1 hour
            if "time" in event_info:
                event_time = event_info["time"]
                now = datetime.datetime.now(datetime.timezone.utc)
                one_hour_from_now = now + datetime.timedelta(hours=1)
                
                # Reject if event starts more than 1 hour in the future
                if event_time > one_hour_from_now:
                    hours_until_event = (event_time - now).total_seconds() / 3600
                    raise ValueError(
                        f"Cannot post yet. Event starts in {hours_until_event:.1f} hours (posts allowed 1 hour before event)."
                    )
                

            if "filenames" in data and "types" in data:
                filename = data["filenames"][0]
                media_type = data["types"][0]
                media_query_result = await conn.create(
                    "media",
                    {
                        "filename": filename,
                        "type": media_type,
                        "event": data["event"],
                        "creator": data["creator"],
                    },
                )
                self.logger.warning(
                    json.dumps(
                        media_query_result, option=json.OPT_INDENT_2, default=str
                    )
                )

            # RELATE after media creation. If RELATE fails we delete the orphaned
            # media record so re-submission isn't blocked by a dangling media row.
            try:
                query = """
                RELATE $users -> posts -> $media SET content = $content, event = $event RETURN VALUE out.id;
                """
                params = {
                    "media": media_query_result["id"],
                    "content": data["content"],
                    "event": data["event"],
                }
                result = await conn.query(query, params)
            except Exception as relate_err:
                if media_query_result.get("id"):
                    try:
                        await conn.delete(media_query_result["id"])
                        self.logger.warning(f"Rolled back orphaned media {media_query_result['id']} after post RELATE failed")
                    except Exception as rollback_err:
                        self.logger.error(f"Media rollback also failed: {rollback_err}")
                raise relate_err
        self.logger.info(json.dumps(result, option=json.OPT_INDENT_2, default=str))
        self.logger.info(f"Media created with ID: {result}")
        return record_id_to_json(result)[0]

    async def delete_post(self, id: str):
        """
        Asynchronously deletes a post associated with the given ID.
        Args:
            id (str): ID of the post to be deleted.
        Returns:
            dict: The result of the deletion operation.
        Raises:
            Exception: If the deletion operation fails.
        """
        async with self.pool.acquire() as conn:
            result = await conn.delete(RecordID("posts", id))
        return record_id_to_json(result)

    async def fetch_post(self, id: str) -> dict:
        """
        Asynchronously fetches a post associated with the given ID.
        Args:
            id (str): ID of the post to be fetched.
        Returns:
            dict: The result of the fetch operation.
        Raises:
            Exception: If the deletion operation fails.
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                    RETURN fn::fetch_post(type::thing('posts', $post_id));
                    """,
                {"post_id": id},
            )
            # result = await conn.select(RecordID("posts", id))
        self.logger.debug(json.dumps(result, option=json.OPT_INDENT_2, default=str))
        return record_id_to_json(result)


async def init_db(app) -> tuple[PostsDB, SurrealDBPoolManager]:
    """
    Initialize the database connection pool and return an PostsDB instance.

    Args:
        app: The Quart application instance

    Returns:
        PostsDB: Initialized database connector
    """
    SCHEMA_FILE = os.getenv("SCHEMA_FILE")
    SURREAL_URI = os.getenv("SURREAL_URI")
    SURREAL_USER = os.getenv("SURREAL_USER")
    SURREAL_PASS = os.getenv("SURREAL_PASS")
    NAMESPACE = "partyscene"
    DATABASE = "partyscene"

    # Create connection pool manager
    pool_manager = SurrealDBPoolManager()

    # Create a connection pool for events service
    pool = await pool_manager.create_pool(
        name="posts_pool",
        uri=SURREAL_URI,
        credentials={"username": SURREAL_USER, "password": SURREAL_PASS},
        namespace=NAMESPACE,
        database=DATABASE,
        min_connections=3,
        max_connections=20,  # Increased from 10 to handle more concurrent requests
        max_idle_time=60,  # Reduced - recycle idle connections faster
        connection_timeout=10.0,  # Increased from 5s to allow slower connection establishment
        acquisition_timeout=30.0,  # Increased from 10s to 30s to prevent premature cancellation
        health_check_interval=10,  # Reduced - check health more frequently
        max_usage_count=100,  # Reduced - recycle connections more aggressively
        connection_retry_attempts=3,
        connection_retry_delay=1.0,
        schema_file=SCHEMA_FILE,
        reset_on_return=True,
        log_queries=True,
    )

    # Create PostsDB instance
    posts_db = PostsDB(pool, app.logger)

    return posts_db, pool_manager