from quart import Quart
from surrealdb import AsyncSurrealDB
import os
from typing import Optional, List, Dict, Any
from ..schema import Events
import logging


class EventsDB:
    def __init__(self, db: AsyncSurrealDB) -> None:
        self.db = db

    async def create(self, data: Events) -> Dict[str, Any]:
        """Create a new event"""
        try:
            result = await self.db.query(
                """
                CREATE events CONTENT {
                    title: $title,
                    description: $description,
                    coordinates: type::point($coordinates),
                    is_private: $is_private,
                    timestamp: $timestamp,
                    price: $price,
                    host: type::thing('users', $host),
                    created_at: time::now(),
                    status: 'scheduled',
                    attendees_count: 0
                };
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
            return result[0]["result"][0]
        except Exception as e:
            logging.error(f"Failed to create event: {str(e)}")
            raise

    async def fetch_by_distance(
        self, 
        coordinates: tuple[float, float], 
        distance: int, 
        *, 
        live: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Fetch all events within a certain distance
        
        Args:
            coordinates (tuple[float, float]): Latitude and longitude
            distance (int): The distance in meters
            live (bool, optional): If True, only return live events
            
        Returns:
            List[Dict[str, Any]]: List of events within the specified distance
        """
        try:
            result = await self.db.query(
                """
                SELECT 
                    *,
                    <-attends<-users AS attendees,
                    array::len(<-attends<-users) as attendees_count,
                    geo::distance(coordinates, type::point($coordinates)) as distance
                FROM events 
                WHERE 
                    is_live = $live 
                    AND geo::distance(coordinates, type::point($coordinates)) <= $distance
                ORDER BY distance ASC;
                """,
                {
                    "live": live,
                    "distance": distance,
                    "coordinates": coordinates
                }
            )
            return result[0]["result"]
        except Exception as e:
            logging.error(f"Failed to fetch events by distance: {str(e)}")
            raise

    async def fetch_all(self) -> List[Dict[str, Any]]:
        """
        Fetch all events with their attendees
        
        Returns:
            List[Dict[str, Any]]: List of all events
        """
        try:
            result = await self.db.query(
                """
                SELECT 
                    *,
                    <-attends<-users AS attendees,
                    array::len(<-attends<-users) as attendees_count
                FROM events
                ORDER BY created_at DESC;
                """
            )
            return result[0]["result"]
        except Exception as e:
            logging.error(f"Failed to fetch all events: {str(e)}")
            raise

    async def fetch(self, event_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single event by ID
        
        Args:
            event_id (str): The event ID to fetch
            
        Returns:
            Optional[Dict[str, Any]]: Event data or None if not found
        """
        try:
            result = await self.db.query(
                """
                SELECT 
                    *,
                    <-attends<-users AS attendees,
                    array::len(<-attends<-users) as attendees_count
                FROM type::thing('events', $event_id);
                """,
                {"event_id": event_id}
            )
            return result[0]["result"][0] if result[0]["result"] else None
        except Exception as e:
            logging.error(f"Failed to fetch event: {str(e)}")
            raise

    async def live_query(self, event_id: str):
        """Start a live query for an event"""
        try:
            query = """
            LIVE SELECT 
                *,
                <-attends<-users AS attendees,
                array::len(<-attends<-users) as attendees_count
            FROM type::thing('events', $event_id)
            FETCH host, attendees;
            """
            return await self.db.query(query, {"event_id": event_id})
        except Exception as e:
            logging.error(f"Failed to create live query: {str(e)}")
            raise

    async def get_live_notifications(self, live_id: str):
        """Get notifications for a live query"""
        return self.db.live_notifications(live_id)

    async def kill_live_query(self, live_id: str):
        """Kill a live query"""
        try:
            await self.db.kill(live_id)
        except Exception as e:
            logging.error(f"Failed to kill live query: {str(e)}")
            raise


async def init_db(app: Quart) -> EventsDB:
    """Initialize database connection"""
    try:
        db = AsyncSurrealDB(app.config["SURREAL_URI"])
        await db.connect()
        
        await db.sign_in(
            username=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD")
        )
        await db.use("partyscene", "partyscene")
        return EventsDB(db)
    except Exception as e:
        logging.error(f"Failed to initialize database: {str(e)}")
        raise
