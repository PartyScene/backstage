from quart import Quart
import os
from surrealdb import AsyncSurreal, Table, RecordID


class MediaDB:

    def __init__(self, db) -> None:
        self.db: AsyncSurreal = db

    async def fetch_media(self, data) -> dict:
        """
        Fetch media record from the database by its unique ID.
        """
        result = await self.db.select(RecordID("media", data["id"]))
        result["id"] = result["id"].id
        return result

    async def delete_media(self, data: dict):
        """This function deletes media data.

        Args:
            data (__dict__): Must contain media ID.
        """
        result = await self.db.delete(RecordID("media", data["id"]))

        return result

    async def create_media_metadata(self, data: dict) -> dict:
        """Uploads media metadata to the database

        Args:
            data (dict): _description_
        """
        query = """
        CREATE media SET type = $type, url = $url, creator = type::thing('users', $creator), event = type::thing('events', $event) RETURN AFTER;
        """
        result = await self.db.query(query, data)
        if "ERR" in result[0]:
            raise Exception(
                f"Error creating media record: {result}"
            )  # Handle error case

        return result


async def init_db(app: Quart) -> MediaDB:
    db = AsyncSurreal(os.environ["SURREAL_URI"])
    await db.connect()
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    await db.signin(
        {"username": os.getenv("DB_USER"), "password": os.getenv("DB_PASSWORD")}
    )
    await db.use("partyscene", "partyscene")
    return MediaDB(db)
