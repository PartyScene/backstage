from quart import Quart
from surrealdb import AsyncSurreal
from surrealdb.data import GeometryPoint, RecordID, Table
import os
from typing import Optional, List, Dict, Any
import logging
from shared.utils import record_id_to_json


class EventsDB:
    def __init__(self, db) -> None:
        self.db: AsyncSurreal = db

    async def create_event(self, data: Dict[str, Any]):
        """Create a new event"""
        logging.info(f"Creating event: {data}")
        try:
            # data['coordinates'] = GeometryPoint(data['coordinates'][0], data["coordinates"][1])
            data["host"] = RecordID("users", data["host"])
            data["location"] = {
                "address": data.get("location"),
                "coordinates": data.pop("coordinates"),
            }

            # result = await self.db.create(Table("events"), data)
            logging.info(f"Creating event: {data}")
            result = await self.db.create("events", data)
            # result = await self.db.query(
            # """
            # CREATE events SET
            #         title = $title,
            #         description = $description,
            #         location.address = $location,
            #         location.coordinates_hash = geo::hash::encode($coordinates),
            #         is_private = $is_private,
            #         price = $price,
            #         categories = $categories,
            #         tags = $tags,
            #         host = $host,
            #         status = 'scheduled'
            #     RETURN AFTER;
            #     """,
            #     {
            #         "title": data.get("title"),
            #         "description": data.get("description"),
            #         "location": data.get("location"),
            #         "coordinates": data.get("coordinates"),
            #         "is_private": data.get("is_private", False),
            #         "price": data['price'],
            #         "categories": data.get("categories", []),
            #         "tags": data.get("tags", []),
            #         "host": data.get("host")
            #     }
            # )
            logging.info(f"Query result: {result}")
            if "ERR" in result:
                raise Exception(f"Error creating event: {result}")  # Handle error case
            return record_id_to_json(result)

        except KeyError:
            logging.error(f"Invalid Params: {data}")
            return
        except Exception as e:
            logging.error(f"Failed to create event: {str(e)}")
            raise

    async def delete_event(self, event_id: str):
        """
        Delete an event by ID

        Args:
            event_id (str): The ID of the event to delete
        """
        result = await self.db.delete(RecordID("events", event_id))
        if "ERR" in result:
            raise Exception(
                f"Error deleting event: {result[0]['result']}"
            )  # Handle error case
        return record_id_to_json(result)

    async def fetch_by_distance(
        self, coordinates: tuple[float, float], distance: int, *, live: bool = False
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
                {"live": live, "distance": distance, "coordinates": coordinates},
            )
            return record_id_to_json(result)

        except Exception as e:
            logging.error(f"Failed to fetch events by distance: {str(e)}")
            raise

    async def fetch_all(self, page: int = 1, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Fetch all events with their attendees

        Returns:
            List[Dict[str, Any]]: List of all events
        """
        try:
            result = await self.db.query(
                """
                     SELECT *,
                        <-attends<-users AS attendees,
                        array::len(<-attends<-users) as attendees_count
                    FROM events ORDER BY created_at DESC LIMIT $limit START ($page - 1) * $limit;
                """,
                {"page": page, "limit": limit},
            )
            logging.info(f"Query result: {result}")
            return record_id_to_json(result)

        except Exception as e:
            logging.error(f"Failed to fetch all events: {str(e)}")
            raise

    async def fetch_all_public(
        self, page: int = 1, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Fetch all public events

        Args:
            page (int, optional): The page number. Defaults to 1.
            limit (int, optional): The number of events per page. Defaults to 20.

        Returns:
            List[Dict[str, Any]]: List of public events
        """
        try:
            result = await self.db.query(
                """
                     SELECT *,
                        <-attends<-users AS attendees,
                        array::len(<-attends<-users) as attendees_count
                    FROM events WHERE is_private = false ORDER BY created_at DESC LIMIT $limit START ($page - 1) * $limit;
                """,
                {"page": page, "limit": limit},
            )
            return record_id_to_json(result)
        except Exception as e:
            logging.error(f"Failed to fetch all public events: {str(e)}")
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
                FROM ONLY type::thing('events', $event_id);
                """,
                {"event_id": event_id},
            )
            return record_id_to_json(result)
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
            return result[0]["result"][0]
        except Exception as e:
            logging.error(f"Failed to create live query: {str(e)}")
            raise

    async def get_live_notifications(self, live_id: str):
        """Get notifications for a live query"""
        return self.db.subscribe_live(live_id)

    async def kill_live_query(self, live_id: str):
        """Kill a live query"""
        try:
            await self.db.kill(live_id)
        except Exception as e:
            logging.error(f"Failed to kill live query: {str(e)}")
            raise

    async def update_event_data(self, event_id: str, data: dict):
        """
        Update the data of an event

        Args:
            event_id (str): The ID of the event to update
            data (dict, optional): metadata to change

        Returns:
            Dict[str, Any]: Updated event data
        """
        result = await self.db.merge(RecordID("events", event_id), data)
        if "ERR" in result:
            raise Exception(f"Error updating event: {result}")  # Handle error case
        logging.info(f"Updated event: {result}")
        result = {"id": result.pop("id").id, "host": result.pop("host").id, **result}
        return result

    async def update_event_status(
        self, event_id: str, status: str, metadata: dict = None
    ) -> Dict[str, Any]:
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
            valid_statuses = ["scheduled", "live", "ended", "cancelled"]
            if status not in valid_statuses:
                raise ValueError(
                    f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                )

            # Build update query
            update_data = {
                "status": status,
                "updated_at": "time::now()",
            }
            if metadata:
                update_data["metadata"] = metadata

            result = await self.db.query(
                """
                UPDATE ONLY type::thing('events', $event_id) MERGE $update_data
                RETURN 
                    *,
                    <-attends<-users AS attendees,
                    array::len(<-attends<-users) as attendees_count;
                """,
                {"event_id": event_id, "update_data": update_data},
            )
            return record_id_to_json(result)

        except Exception as e:
            logging.error(f"Failed to update event status: {str(e)}")
            raise

    async def create_attendance(self, data: Dict[str, Any]):
        """Create an attendance relationship between user and event"""
        try:
            await self.db.let("user", RecordID("users", data["user"]))
            await self.db.let("event", RecordID("events", data["event"]))
            query = """
            RELATE $user -> attends -> $event SET status = $status;
            """
            result = await self.db.query(query, {"status": data["status"]})
            if result[0]["status"] == "ERR":
                raise Exception(
                    f"Error creating attendance: {result[0]['result']}"
                )  # Handle error case
        except Exception as e:
            logging.error(f"Failed to create attendance: {str(e)}")
            raise


async def init_db(app: Quart) -> EventsDB:
    """Initialize database connection"""
    try:
        db = AsyncSurreal(os.environ["SURREAL_URI"])
        await db.connect()

        await db.signin(
            {"username": os.getenv("DB_USER"), "password": os.getenv("DB_PASSWORD")}
        )
        await db.use("partyscene", "partyscene")
        return EventsDB(db)
    except Exception as e:
        logging.error(f"Failed to initialize database: {str(e)}")
        raise
