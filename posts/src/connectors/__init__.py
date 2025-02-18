from quart import Quart
import os
from surrealdb import AsyncSurreal


class PostsDB:
    def __init__(self, db) -> None:
        self.db: AsyncSurreal = db

    async def create_post(self, content, media_links, author) -> dict:
        """
        Asynchronously creates a new post in the database.
            Args:
                content (str): The content of the post.
                media_links (list): A list of media links associated with the post.
                author (str): The ID of the author creating the post.
            Returns:
                dict: A dictionary containing the result of the post creation query.
        """
        query = """
        CREATE post SET content = $content, media_links = $media_links, author = type::thing('users', $author)
        """
        params = {
            "content": content,
            "media_links": media_links,
            "author": author
        }
        result = await self.db.query(
           query, params
        )
        return result[0]["result"][0]

    async def delete_post(self, data):
        """
        Asynchronously deletes a post associated with the given data.
        Args:
            data (dict): ### post to be deleted.
        Returns:
            dict: The result of the deletion operation.
        Raises:
            Exception: If the deletion operation fails.
        """
        
        result = await self.db.query(
           # 
        )
        return result[0]["result"][0]

async def init_db(app: Quart) -> PostsDB:
    db = AsyncSurreal(app.config["SURREAL_URI"])
    await db.connect()
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    await db.signin({
            "username": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD")
        })
    await db.use("partyscene", "partyscene")
    return PostsDB(db)
