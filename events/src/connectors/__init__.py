from quart import Quart
from surrealdb import Surreal

# from src.schema import FormIn


class EventsDB:
    def __init__(self, db) -> None:
        self.db: Surreal = db
        self.events = self.Events(db)
        
    class Events:
        def __init__(self, db) -> None:
            self.db: Surreal = db
        
        async def fetch_all(self) -> list:
            """Fetch all Events
            """
            result = await self.db.query("SELECT *, <-attends<-users AS attendees FROM events;")
            return result[0]['result']
            
        async def create(self):
            ...

    # async def _login(self, password):
    #     result = await self.db.query(
    #         "SELECT * FROM users WHERE crypto::bcrypt::compare(password, $password);",
    #         {"password": password},
    #     )

    # async def _create(self, form: FormIn):
    #     result = await self.db.query(
    #         "INSERT INTO users (first_name, last_name, email, password) VALUES ($fname, $lname, $email, crypto::bcrypt::generate($pwd))",
    #         {
    #             "fname": form.first_name,
    #             "lname": form.last_name,
    #             "email": form.email,
    #             "pwd": form.password,
    #         },
    #     )
        

async def init_db(app: Quart) -> EventsDB:
    db = Surreal(app.config["SURREAL_URI"])
    await db.connect()
    await db.signin(
        {
            "user": "root",
            "pass": "rootrm",
        }
    )
    await db.use("partyscene", "partyscene")
    return EventsDB(db)
