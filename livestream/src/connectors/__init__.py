from quart import Quart
from surrealdb import AsyncSurrealDB
import os

class LiveStreamDB:
    def __init__(self, db) -> None:
        self.db: AsyncSurrealDB = db
    
    async def fetch_livestream(self, event_id: str):
        """
        Get the current livestream data attached to an event
        """
        result = await self.db.query(
            "SELECT * FROM livestreams WHERE event = $event_id",
            {"event_id": event_id}
        )
        return result[0]["result"][0]
    
    async def store_livestream(self, channel_id, ingest_url, playback_url, event_id: str):
        """
        Store the ingest url / playback url / from GCP and attach it to the event.

        Returns:
            bool: Indicates if this operation was a success
        """
        result = await self.db.query(
            """
            INSERT INTO livestreams 
                (channel_id, input_id, ingest_url, playback_url, event) VALUES ($channel_id, $input_id, $ingest_url, $playback_url, $event)
            """,
            {"channel_id": channel_id, "ingest_url": ingest_url, "playback_url": playback_url, "event": event_id},
        )
        return result[0]["result"][0]

    # async def delete(self, email) :
    #     """This db function deletes a user.

    #     Args:
    #         email (__string_): The user email to delete.
    #     """
    #     result = await self.db.query(
    #         "DELETE users WHERE email = $email;", {"email": email}
    #     )
    #     return result[0]["result"][0]

    # async def update(self, data: dict):
    #     """This function updates a specific field

    #     Args:
    #         data (dict): _description_
    #     """
    #     record_id = (
    #         await self.db.query(
    #             "SELECT id FROM users WHERE email = $email;",
    #             {"email": data["email"]},
    #         )
    #     )[0]["result"][0]["id"]
    #     result = await self.db.query(
    #         "UPDATE $record_id MERGE $content",
    #         {"content": data, "record_id": record_id},
    #     )
    #     return result


async def init_db(app: Quart) -> LiveStreamDB:
    db = AsyncSurrealDB(app.config["SURREAL_URI"])
    await db.connect()
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    await db.sign_in(username=DB_USER, password=DB_PASSWORD)
    await db.use("partyscene", "partyscene")
    return LiveStreamDB(db)
