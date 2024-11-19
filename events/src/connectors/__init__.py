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
            
        async def fetch_by_distance(self, location, distance: int, *, live : bool = False) -> list:
            """Fetch all events within a certain distance

            Args:
                distance (int, required): The distance in meters
                location (Point)
                live (bool, optional): If set to True, only live events selected. Defaults to False.
            """
            result = await self.db.query(
                "SELECT *, <-attends<-users AS attendees FROM events "
                "WHERE is_live = $live " 
                "AND geo::distance(location, type::point($location)) <= $distance;",
                {
                    "live": live,
                    "distance": distance,
                    "location": location
                }
            )
            return result[0]["result"]

        
        async def fetch_all(self) -> list:
            """Fetches all parties / events / scenes.

            Returns:
                list: array containing parties.
            """
            result = await self.db.query(
                "SELECT *, <-attends<-users AS attendees FROM events;"
            )
            return result[0]["result"]


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
