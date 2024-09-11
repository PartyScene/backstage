from surrealdb import Surreal


class AuthDB:
    def __init__(self, db) -> None:
        self.db: Surreal = db

    async def _login(self, password):
        result = await self.db.query(
            """
            SELECT * FROM users WHERE crypto::scrypt::compare(password, $password);
                                     """,
            {"password": password},
        )

    async def _create(self, form):
        result = await self.db.create(
            "users",
            {
                "email": form["email"],
                "first_name": form["first_name"],
                "last_name": form["last_name"],
                "password": f"crypto::scrypt::generate({form['password']})",
            },
        )

        # Assign the variable on the connection


# result = await self.db.query('CREATE users; SELECT * FROM type::table($tb)', {
# 	'tb': 'person',
# })
# # Get the first result from the first query
# result[0]['result'][0]
# # Get all of the results from the second query
# result[1]['result']


async def init_db(app) -> AuthDB:
    db = Surreal(app.config["SURREAL_URI"])
    await db.connect()
    await db.signin(
        {
            "user": "root",
            "pass": "rootrm",
        }
    )
    return AuthDB(db)
