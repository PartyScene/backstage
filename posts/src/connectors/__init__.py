from quart import Quart
import os
import json

from surrealdb import AsyncSurreal, RecordID
from shared.utils import record_id_to_json

import logging
logger = logging.getLogger(__name__)

class PostsDB:
    def __init__(self, db) -> None:
        self.db: AsyncSurreal = db
    
    
    async def fetch_event_posts(self, id: str) -> dict:
        """
        Asynchronously fetches all posts associated with the given event.
            Args:
                id (str): The ID of the event.
            Returns:
                dict: A dictionary containing the result of the post fetch query.
        """
        query = """
                SELECT ->posts[WHERE event = type::thing('events', $id)]
                FROM users;
            """
        params = {"id": id}
        result = (await self.db.query(query, params))[0]
        logger.info(json.dumps(result, indent=4, default=str))
        return record_id_to_json(result)

    async def create_comment(self, data):
        """
        Asynchronously creates a new comment in the database.
            Args:
                data (dict): A dictionary containing the comment data.
            Returns:
                dict: A dictionary containing the result of the comment creation query.
        """
        await self.db.let("user", RecordID("users", data["author"]))
        await self.db.let("post", RecordID("posts", data["post"]))
        query = """
        RELATE $user -> comments -> $post SET content = $content
        """
        params = {"content": data["content"]}
        result = await self.db.query(query, params)
        return result[0]

    async def fetch_comments(self, post_id: str) -> dict:
        """
        Asynchronously fetches all comments associated with the given post.
            Args:
                post_id (str): The ID of the post.
            Returns:
                dict: A dictionary containing the result of the comment fetch query.
        """
        query = """
                SELECT ->comments(WHERE out = type::thing('posts', $post_id)
                FROM users;
            """
        params = {"post_id": post_id}
        result = await self.db.query(query, params)
        return result[0]

    async def delete_comment(self, data):
        """
        Asynchronously deletes a post associated with the given data.
        Args:
            data (dict): post data to be deleted, must include SurrealDB ID.
        Returns:
            dict: The result of the deletion operation.
        Raises:
            Exception: If the deletion operation fails.
        """

        result = await self.db.delete(RecordID("comments", data["id"]))
        return result[0]["result"][0]

    
    async def create_post(self, data, media_links, author) -> dict:
        """
        Asynchronously creates a new post in the database.
            Args:
                data (dict): A dictionary containing the post data.
                media_links (list): A list of media links associated with the post.
                author (str): The ID of the author creating the post.
            Returns:
                dict: A dictionary containing the result of the post creation query.
        """
        await self.db.let("users", RecordID("users", author))
        await self.db.let("media", [RecordID("media", media["id"]) for media in media_links])
        query = """
        RELATE ONLY $users -> posts -> $media SET content = $content, media_links = $media_links, event = $event;
        """
        params = {
            "content": data["content"],
            "media_links": media_links,
            "event": RecordID("events", data["event"]),
        }
        result = await self.db.query(query, params)
        logger.info(json.dumps(result, indent=4, default=str))
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

        result = await self.db.delete(RecordID("posts", id))
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

        result = await self.db.select(RecordID("posts", id))
        if not result:
            return None
        logger.debug(json.dumps(result, indent=4, default=str))
        return record_id_to_json(result)


async def init_db(app: Quart) -> PostsDB:
    db = AsyncSurreal(os.environ["SURREAL_URI"])
    await db.connect()
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    await db.signin(
        {"username": os.getenv("DB_USER"), "password": os.getenv("DB_PASSWORD")}
    )
    await db.use("partyscene", "partyscene")
    return PostsDB(db)
