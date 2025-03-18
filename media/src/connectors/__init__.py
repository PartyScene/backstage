from quart import Quart
import os
from surrealdb import AsyncSurreal, Table, RecordID
from shared.utils import record_id_to_json


class MediaDB:

    def __init__(self, db) -> None:
        self.db: AsyncSurreal = db

    async def close(self):
        self.db.close()

    async def fetch_media(self, data) -> dict:
        """
        Fetch media record from the database by its unique ID.
        """
        result = await self.db.select(RecordID("media", data["id"]))
        return record_id_to_json(result)

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
        CREATE ONLY media SET type = $type, filename = $filename, creator = type::thing('users', $creator), event = type::thing('events', $event) RETURN AFTER;
        """
        result = await self.db.query(query, data)
        if "ERR" in result:
            raise Exception(
                f"Error creating media record: {result}"
            )  # Handle error case
        return record_id_to_json(result)


async def init_db(app: Quart) -> MediaDB:
    db = AsyncSurreal(os.getenv("SURREAL_URI"))
    
    await db.signin(
        {"username": os.getenv("SURREAL_USER"), "password": os.getenv("SURREAL_PASS")}
    )
    await db.use("partyscene", "partyscene")
    return MediaDB(db)
