from quart import Quart
import os
from surrealdb import AsyncSurrealDB, Table


class MediaDB:
    
    def __init__(self, db) -> None:
        self.db: AsyncSurrealDB = db

    async def fetch_media(self, email) -> dict:
        """
        Fetch media record from the database by its unique ID.
        """
        result = await self.db.query(
            "SELECT *, ->attends->events[where true] AS scenes FROM users WHERE email = $email;",
            {"email": email},
        )
        return result[0]["result"][0]

    async def delete_media(self, email):
        """This db function deletes a user.

        Args:
            email (__string_): The user email to delete.
        """
        result = await self.db.query(
            "DELETE users WHERE email = $email;", {"email": email}
        )
        return result[0]["result"][0]

    async def upload_media(self, data: dict) -> dict:
        """Uploads media metadata to the database

        Args:
            data (dict): _description_
        """
        query = """
        CREATE media SET type = $type, url = $url, creator = type::thing('users', $creator), event = type::thing('events', $event);
        """
        result = await self.db.query(query, data)
        if result[0]['status'] == 'ERR':
            raise Exception(f"Error creating media record: {result[0]['result']}")  # Handle error case
        
        return result[0]["result"][0]


async def init_db(app: Quart) -> MediaDB:
    db = AsyncSurrealDB(app.config["SURREAL_URI"])
    await db.connect()
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    await db.sign_in(username=DB_USER, password=DB_PASSWORD)
    await db.use("partyscene", "partyscene")
    return MediaDB(db)
