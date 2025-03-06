import os

from surrealdb import AsyncSurreal
from shared.utils import record_id_to_json

import json
import logging
# Get the logger
logger = logging.getLogger(__name__)


class AuthDB:

    def __init__(self, db: AsyncSurreal) -> None:
        self.db = db

    async def _login(self, data) -> dict:
        try:
            result = (
                await self.db.query(
                    "SELECT * FROM users WHERE crypto::bcrypt::compare(password, $password) AND email = $email;",
                    {"password": data["password"], "email": data["email"]},
                )
            )[0]
        except IndexError:
            return False
        return record_id_to_json(result)
    
    
    async def _create_user(self, form):
        try:
            result = await self.db.create("users", form)
        except:
            return False
        logger.info(json.dumps(result, indent=4, default=str))
        return record_id_to_json(result)
        # Assign the variable on the connection


# result = await self.db.query('CREATE users; SELECT * FROM type::table($tb)', {
# 	'tb': 'person',
# })
# # Get the first result from the first query
# result[0]['result'][0]
# # Get all of the results from the second query
# result[1]['result']


async def init_db(app) -> AuthDB:
    SCHEMA_FILE = os.getenv("SCHEMA_FILE")
    db = AsyncSurreal(os.getenv("SURREAL_URI"))
    await db.connect()

    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    await db.signin(
        {"username": os.getenv("DB_USER"), "password": os.getenv("DB_PASSWORD")}
    )
    await db.use("partyscene", "partyscene")

    # Load and execute schema file
    with open(SCHEMA_FILE, "r") as file:
        schema = file.read()
        commands = [cmd.strip() for cmd in schema.split(";") if cmd.strip()]
        for cmd in commands:
            await db.query(cmd)

    return AuthDB(db)