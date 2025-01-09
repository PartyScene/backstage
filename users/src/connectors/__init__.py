from quart import Quart
from surrealdb import AsyncSurrealDB
import os


class UsersDB:
    def __init__(self, db) -> None:
        self.db: AsyncSurrealDB = db
        self.users = self.Users(db)

    class Users:
        def __init__(self, db) -> None:
            self.db: AsyncSurrealDB = db

        async def find_friend_relationship(self, data: dict, degree: int = None):
            """
            Find a friend relationship between two users.

            Args:
                data (dict, required): The friend relationship data object containing the two users.
                degree (int, required): The degree of separation between the two users.
            """
            match degree:
                case 1:
                    result = await self.db.query(
                        "SELECT ->friends->users FROM type::thing('users', $origin)",
                        {"origin": data["origin"]},
                    )
                case 2:
                    result = await self.db.query(
                        "LET $origin = type::thing('users', $origin)"
                        "SELECT ->friends->users->friends->users as mutuals FROM origin"
                        "AND mutuals NOT IN (SELECT ->friends->users FROM origin)",
                        {"origin": data["origin"]},
                    )
                case _:
                    return [{"result": "Degree must be specified."}]

            return result[0]["result"]

        async def create_friend_relationship(self, data: dict):
            """
            Create a friend relationship between two users.

            Args:
                data (dict, required): The friend relationship data object containing the two users.
            """
            result = await self.db.query(
                """
                RELATE type::thing('users', $origin) -> friends -> type::thing('users', $target)
                """,
                {"origin": data["origin"], "target": data["target"]},
            )
            return result[0]["result"]

        async def fetch(self, id):
            """
            Fetch one user
            """
            result = await self.db.query(
                "SELECT *, ->attends->events[where true] AS scenes FROM users WHERE id = type::thing('users', $id);",
                {"id": id},
            )
            return result[0]["result"][0]

        async def delete(self, id):
            """This db function deletes a user.

            Args:
                email (__string_): The user email to delete.
            """
            result = await self.db.query(
                "DELETE users WHERE id = type::thing('users', $id);", {"id": id}
            )
            return result[0]["result"][0]

        async def update(self, data: dict):
            """This function updates a specific field

            Args:
                data (dict): _description_
            """
            result = await self.db.query(
                "UPDATE $record_id MERGE $content",
                {"content": data, "record_id": data["user"]},
            )
            return result


async def init_db(app: Quart) -> UsersDB:
    db = AsyncSurrealDB(app.config["SURREAL_URI"])
    await db.connect()

    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    await db.sign_in(username=DB_USER, password=DB_PASSWORD)
    await db.use("partyscene", "partyscene")
    return UsersDB(db)
