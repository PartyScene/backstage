from quart import Quart
from surrealdb import Surreal


class PostsDB:
    def __init__(self, db) -> None:
        self.db: Surreal = db

    async def create_post(self, content, media_links, author) -> dict:
        """
        Asynchronously creates a new post with the given data.
        Args:
            data (dict): The data for the new post, including content, media links, and author.
        Returns:
            dict: The result of the creation operation.
        Raises:
            Exception: If the creation operation fails.
        """
        query = """
        CREATE post SET content = $content, media_links = $media_links, author = $author
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
    db = Surreal(app.config["SURREAL_URI"])
    await db.connect()
    await db.signin(
        {
            "user": "root",
            "pass": "rootrm",
        }
    )
    await db.use("partyscene", "partyscene")
    return PostsDB(db)
