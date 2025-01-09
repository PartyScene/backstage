from quart import Quart
from surrealdb import AsyncSurrealDB
import os
from ..schema import Events


class EventsDB:
    def __init__(self, db) -> None:
        self.db: AsyncSurrealDB = db
        self.events = self.Events(db)

    class Events:
        def __init__(self, db) -> None:
            self.db: AsyncSurrealDB = db
        
        async def create(self, data: Events):
            """
            Create a new event

            Args:
                data (Events, required): The event data object containing event details
            """
            result = await self.db.query(
                """
                INSERT INTO events (title, description, coordinates, is_private, timestamp, price, host)
                VALUES ($title, $description, $coordinates, $is_private, $timestamp, $price, type::thing('users', $host))
                """,
                {
                    "title": data.title,
                    "description": data.description,
                    "coordinates": data.coordinates,
                    "is_private": data.is_private,
                    "timestamp": data.timestamp,
                    "price": data.price,
                    "host": data.host
                    
                 }
            )
            return result[0]["result"]
        
        
        async def fetch_by_distance(self, coordinates, distance: int, *, live : bool = False) -> list:
            """
            Fetch all events within a certain distance

            Args:
                distance (int, required): The distance in meters
                coordinates (Point)
                live (bool, optional): If set to True, only live events selected. Defaults to False.
            """
            result = await self.db.query(
                "SELECT *, <-attends<-users AS attendees FROM events "
                "WHERE is_live = $live " 
                "AND geo::distance(coordinates, type::point($coordinates)) <= $distance;",
                {
                    "live": live,
                    "distance": distance,
                    "location": coordinates
                }
            )
            return result[0]["result"]
        

        
        async def fetch_all(self) -> list:
            """
            Fetches all parties / events / scenes.

            Returns:
                list: array containing parties.
            """
            result = await self.db.query(
                "SELECT *, <-attends<-users AS attendees FROM events;"
            )
            return result[0]["result"]


async def init_db(app: Quart) -> EventsDB:
    db = AsyncSurrealDB(app.config["SURREAL_URI"])
    await db.connect()
    
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    await db.sign_in(username=DB_USER, password=DB_PASSWORD)
    await db.use("partyscene", "partyscene")
    return EventsDB(db)
