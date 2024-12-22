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

        async def fetch(self, email) -> dict:
            """
            Fetch one user
            """
            result = await self.db.query(
                "SELECT *, ->attends->events[where true] AS scenes FROM users WHERE email = $email;",
                {"email": email},
            )
            return result[0]["result"][0]

        async def delete(self, email):
            """This db function deletes a user.

            Args:
                email (__string_): The user email to delete.
            """
            result = await self.db.query(
                "DELETE users WHERE email = $email;", {"email": email}
            )
            return result[0]["result"][0]

        async def update(self, data: dict):
            """This function updates a specific field

            Args:
                data (dict): _description_
            """
            record_id = (
                await self.db.query(
                    "SELECT id FROM users WHERE email = $email;",
                    {"email": data["email"]},
                )
            )[0]["result"][0]["id"]
            result = await self.db.query(
                "UPDATE $record_id MERGE $content",
                {"content": data, "record_id": record_id},
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
