from surrealdb import AsyncSurrealDB
import os

class AuthDB:
    def __init__(self, db) -> None:
        self.db: AsyncSurrealDB = db

    async def _login(self, data) -> dict:
        result = await self.db.query(
            "SELECT * FROM users WHERE crypto::bcrypt::compare(password, $password) AND email = $email;",
            {"password": data['password'], "email": data["email"]},
        )
        assert result[0]["result"][0]["email"] == data['email']
        return result[0]["result"][0]

    async def _create(self, form):
        result = await self.db.query(
            "INSERT INTO users (first_name, last_name, email, password) VALUES ($fname, $lname, $email, crypto::bcrypt::generate($pwd))",
            {
                "fname": form['first_name'],
                "lname": form['last_name'],
                "email": form['email'],
                "pwd": form['password'],
            },
        )
        return result[0]
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

    db = AsyncSurrealDB(app.config["SURREAL_URI"])
    await db.connect()
    
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    await db.sign_in(username=DB_USER, password=DB_PASSWORD)
    await db.use("partyscene", "partyscene")
    
        # Load and execute schema file
    with open(SCHEMA_FILE, "r") as file:
        schema = file.read()
        commands = [cmd.strip() for cmd in schema.split(";") if cmd.strip()]
        for cmd in commands:
            await db.query(cmd)
            
    return AuthDB(db)
