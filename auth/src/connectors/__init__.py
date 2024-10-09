from surrealdb import Surreal

from src.schema import FormIn, LoginForm


class AuthDB:
    def __init__(self, db) -> None:
        self.db: Surreal = db

    async def _login(self, data: LoginForm):
        result = await self.db.query(
            "SELECT * FROM users WHERE crypto::bcrypt::compare(password, $password);",
            {"password": data.password},
        )
        return result[0]['result'][0]['email'] == data.email

    async def _create(self, form: FormIn):
        result = await self.db.query(
            "INSERT INTO users (first_name, last_name, email, password) VALUES ($fname, $lname, $email, crypto::bcrypt::generate($pwd))",
            {
                "fname": form.first_name,
                "lname": form.last_name,
                "email": form.email,
                "pwd": form.password,
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
    await db.use("partyscene", "partyscene")
    return AuthDB(db)
