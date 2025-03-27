from quart import Quart
import os
import json

from surrealdb import AsyncSurreal, RecordID
from shared.utils import record_id_to_json
from purreal import SurrealDBConnectionPool, SurrealDBPoolManager

class PostsDB:
    def __init__(self, pool: SurrealDBConnectionPool, logger) -> None:
        self.pool = pool
        self.logger = logger

    async def _info(self):
        """Get database information."""
        return await self.pool.execute_query("INFO FOR DB")
        
    async def fetch_event_posts(self, id: str) -> dict:
        """
        Asynchronously fetches all posts associated with the given event.
            Args:
                id (str): The ID of the event.
            Returns:
                dict: A dictionary containing the result of the post fetch query.
        """
        query = """
                SELECT VALUE ->posts.*
                FROM users WHERE ->posts[WHERE event == type::thing('events', $event_id)];
            """
        params = {"event_id": id}
        async with self.pool.acquire() as conn:
            result = await conn.query(query, params)
        self.logger.info(json.dumps(result, indent=4, default=str))
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

    async def fetch_comments(self, post_id: str) -> dict:
        """
        Asynchronously fetches all comments associated with the given post.
            Args:
                post_id (str): The ID of the post.
            Returns:
                dict: A dictionary containing the result of the comment fetch query.
        """
        query = """ SELECT ->comments.* FROM users WHERE ->comments[WHERE out = type::thing('posts', $post_id)];"""
        params = {"post_id": post_id}
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
            query = """
            RELATE ONLY $users -> posts -> $media SET content = $content, event = $event;
            """
            params = {
                "content": data["content"],
                "event": RecordID("events", data["event"]),
            }
            result = await conn.query(query, params)
        self.logger.info(json.dumps(result, indent=4, default=str))
        return record_id_to_json(result)

    async def create_postand_precreate_media(self, data, author) -> dict:
        """
        Asynchronously creates media relationship first, then a new post in the database.
            Args:
                data (dict): A dictionary containing the post data.
                author (str): The ID of the author creating the post.
            Returns:
                dict: A dictionary containing the result of the post creation query.
        """
        async with self.pool.acquire() as conn:
            await conn.let("users", RecordID("users", author))
            media_ids = await conn.query("RETURN fn::media::create($filenames, $type, $creator, $event)", data)
            await conn.let("media", [RecordID("media", id) for id in media_ids])

            query = """
            RELATE ONLY $users -> posts -> $media SET content = $content, event = $event;
            """
            params = {
                "content": data["content"],
                "event": RecordID("events", data["event"]),
            }
            result = await conn.query(query, params)
        self.logger.info(json.dumps(result, indent=4, default=str))
        return record_id_to_json(result)

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
            result = await conn.select(RecordID("posts", id))
        self.logger.debug(json.dumps(result, indent=4, default=str))
        return record_id_to_json(result)


async def init_db(app) -> PostsDB:
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
        min_connections=2,
        max_connections=10,
        max_idle_time=300,
        connection_timeout=5.0,
        acquisition_timeout=10.0,
        health_check_interval=30,
        max_usage_count=1000,
        connection_retry_attempts=3,
        connection_retry_delay=1.0,
        schema_file=SCHEMA_FILE,
        reset_on_return=True,
        log_queries=True,
    )

    # Create PostsDB instance
    posts_db = PostsDB(pool, app.logger)

    return posts_db, pool_manager
