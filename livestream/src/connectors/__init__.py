from quart import Quart
from surrealdb import AsyncSurreal
import os

from shared.utils import record_id_to_json


class LiveStreamDB:
    def __init__(self, db) -> None:
        self.db: AsyncSurreal = db

    async def close(self):
        self.db.close()

    async def fetch_livestream(self, event_id: str):
        """
        Get the current livestream data attached to an event
        """
        result = await self.db.query(
            """
        SELECT * FROM ONLY livestreams WHERE event = type::thing("events", $event_id)
        """,
            {"event_id": event_id},
        )
        return record_id_to_json(result)

    async def store_livestream(self, channel_response, input_response, event_id: str):
        """
        Store the ingest url / playback url / from GCP and attach it to the event.

        Returns:
            bool: Indicates if this operation was a success
        """
        result = await self.db.query(
            """
            INSERT INTO livestreams 
                (channel_name, input_name, ingest_url, playback_url, manifests, event) VALUES ($channel_name, $input_name, $ingest_url, $playback_url, $manifests, type::thing("events", $event_id))
            """,
            {
                "channel_name": channel_response.name,
                "input_name": input_response.name,
                "ingest_url": input_response.uri,
                "playback_url": channel_response.output.uri,
                "manifests": [x.file_name for x in channel_response.manifests],
                "event_id": event_id,
            },
        )
        return result[0]

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
    db = AsyncSurreal(os.environ["SURREAL_URI"])
    await db.connect()
    await db.signin(
        {"username": os.getenv("SURREAL_USER"), "password": os.getenv("SURREAL_PASS")}
    )
    await db.use("partyscene", "partyscene")
    return LiveStreamDB(db)
