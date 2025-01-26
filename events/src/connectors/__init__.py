from quart import Quart
from surrealdb import AsyncSurrealDB, Table, GeometryPoint, RecordID
import os
from typing import Optional, List, Dict, Any
from ..schema import Events
import logging


class EventsDB:
    def __init__(self, db: AsyncSurrealDB) -> None:
        self.db = db

    async def create_event(self, data: Dict[str, Any]):
        """Create a new event"""
        logging.info(f"Creating event: {data}")
        try:
            data['coordinates'] = GeometryPoint(data['coordinates'][0], data["coordinates"][1])
            data['host'] = RecordID('users', data['host'])
            data['price'] = float(data["price"])

            # result = await self.db.create(Table("events"), data)
            result = await self.db.query(
                        """
                        INSERT INTO events {
                            "title": $title,
                            "description": $description,
                            "coordinates": $coordinates,
                            "is_private": $is_private,
                            "price": $price,
                            "categories": $categories,
                            "tags": $tags,
                            "host": $host,
                            "status": 'scheduled'
                        } RETURN VALUE id;
                        """,
                        {
                            "title": data.get("title"),
                            "description": data.get("description"),
                            "coordinates": data.get("coordinates"),
                            "is_private": data.get("is_private", False),
                            "price": data['price'],
                            "categories": data.get("categories", []),
                            "tags": data.get("tags", []),
                            "host": data.get("host")
                        }
                    )
            logging.info(f"Query result: {result}")
            if result[0]['status'] == 'ERR':
                raise Exception(f"Error creating event: {result[0]['result']}")  # Handle error case
            
            created_event = result[0]["result"][0]
            logging.info(f"Created event: {created_event}")
            return created_event
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
                    id,
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
                    id,
                    host,
                    <-attends<-users AS attendees,
                    array::len(<-attends<-users) as attendees_count
                FROM events;
                -- ORDER BY created_at DESC;
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
                    host,
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
            result = await self.db.query(query, {"event_id": event_id})
            return result[0]['result'][0]
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

    async def update_event_status(self, event_id: str, status: str, metadata: dict = None) -> Dict[str, Any]:
        """
        Update the status of an event and optionally add metadata
        
        Args:
            event_id (str): The ID of the event to update
            status (str): The new status ('scheduled', 'live', 'ended', 'cancelled')
            metadata (dict, optional): Additional metadata about the status change
            
        Returns:
            Dict[str, Any]: Updated event data
        """
        try:
            # Validate status
            valid_statuses = ['scheduled', 'live', 'ended', 'cancelled']
            if status not in valid_statuses:
                raise ValueError(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
            
            # Build update query
            update_data = {
                "status": status,
                "updated_at": "time::now()",
            }
            if metadata:
                update_data["metadata"] = metadata
                
            result = await self.db.query(
                """
                UPDATE type::thing('events', $event_id) MERGE $update_data
                RETURN 
                    *,
                    <-attends<-users AS attendees,
                    array::len(<-attends<-users) as attendees_count;
                """,
                {
                    "event_id": event_id,
                    "update_data": update_data
                }
            )
            return result[0]["result"][0]
            
        except Exception as e:
            logging.error(f"Failed to update event status: {str(e)}")
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
