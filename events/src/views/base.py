from datetime import datetime
import random
import orjson as json
import asyncio
import os
import uuid

from typing import AsyncGenerator, Dict, Any, Tuple, Optional
from http import HTTPStatus

from dataclasses import dataclass
from pprint import pprint
from quart import (
    Response,
    make_response,
    render_template,
    current_app as app,
    request,
    jsonify,
    websocket,
)
import decimal

from events.src.connectors import EventsDB
from shared.classful import route, QuartClassful

from quart_jwt_extended import jwt_required, get_jwt_identity
from aiocache import cached

from shared.workers.rmq import RMQBroker
import uuid_utils as ruuid

from surrealdb import RecordID


class BaseView(QuartClassful):

    def __init__(self):
        self.conn: EventsDB = app.conn
        self.redis = app.redis

    async def _store_live_query(self, event_id: str, live_id: str):
        """Store live query ID in Redis"""
        key = f"live_query:{event_id}"
        await self.redis.set(key, live_id, ex=36000)  # Expire after 10 hours

    async def _get_live_query(self, event_id: str) -> str:
        """Get live query ID from Redis"""
        key = f"live_query:{event_id}"
        return await self.redis.get(key)

    async def _remove_live_query(self, event_id: str):
        """Remove live query ID from Redis"""
        key = f"live_query:{event_id}"
        await self.redis.delete(key)

    @route("/", methods=["GET"])
    async def index(self):
        return await self.healthcheck()

    @route("/events/health", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def healthcheck(self):
        """
        Simple health check endpoint that verifies service and dependency status.
        Returns 200 OK if everything is healthy, 503 Service Unavailable otherwise.
        """
        health_status = {
            "service": "microservices.events",
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "dependencies": {"database": "unknown", "redis": "unknown"},
        }
        message = "Service is healthy"
        status_code = HTTPStatus.OK

        # Check database connection
        try:
            db_info = await self.conn._info()
            health_status["dependencies"]["database"] = "healthy"
        except Exception as e:
            app.logger.error(f"Database health check failed: {e}")
            health_status["dependencies"]["database"] = "unhealthy"
            health_status["status"] = "degraded"
            message = "Service degraded: Database connection failed"
            status_code = HTTPStatus.SERVICE_UNAVAILABLE


        # Check Redis connection
        try:
            redis_ping = await self.redis.ping()
            health_status["dependencies"]["redis"] = (
                "healthy" if redis_ping else "unhealthy"
            )
            if not redis_ping:
                health_status["status"] = "degraded"
                message = "Service degraded: Redis connection failed"
                status_code = HTTPStatus.SERVICE_UNAVAILABLE
        except Exception as e:
            app.logger.error(f"Redis health check failed: {e}")
            health_status["dependencies"]["redis"] = "unhealthy"
            health_status["status"] = "degraded"
            message = "Service degraded: Redis connection failed"
            status_code = HTTPStatus.SERVICE_UNAVAILABLE


        return jsonify(data=health_status, message=message, status=status_code.phrase), status_code

    @route("/events/<event_id>", methods=["GET"])
    @jwt_required
    async def fetch_event(self, event_id):
        """This endpoints returns a specific event"""
        return await self.fetch_events(event_id)

    @route("/events", methods=["GET"])
    @jwt_required
    async def fetch_events(self, event_id=None):
        """This endpoints returns all the events"""
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 20))

        try:
            if event_id:
                if result := await self.conn.fetch(event_id):
                    status_code = HTTPStatus.OK
                    return jsonify(data=result, message="Event fetched successfully.", status=status_code.phrase), status_code
                status_code = HTTPStatus.NOT_FOUND
                return jsonify(message="Event not found", status=status_code.phrase), status_code

            if any([x in request.args for x in ("lat", "lng")]):
                # They requested for Lat Lng soo
                try:
                    location = (
                        float(request.args.get("lat", 0)),
                        float(request.args.get("lng", 0)),
                    )
                    distance = int(request.args.get("distance", 1000))
                except ValueError:
                    status_code = HTTPStatus.BAD_REQUEST
                    return jsonify(message="Invalid latitude, longitude, or distance parameters.", status=status_code.phrase), status_code
                
                result = await self.conn.fetch_by_distance(location, distance)
                status_code = HTTPStatus.OK
                return jsonify(data=result, message="Events fetched by distance successfully.", status=status_code.phrase), status_code

            result = await self.conn.fetch_all(page, limit)
            status_code = HTTPStatus.OK
            return jsonify(data=result, message="Events fetched successfully.", status=status_code.phrase), status_code
        except Exception as e:
            app.logger.error(f"Error fetching events: {str(e)}", exc_info=True)
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return jsonify(message=f"Failed to fetch events: {str(e)}", status=status_code.phrase), status_code


    @route("/events/<event_id>", methods=["PATCH"])
    @jwt_required
    async def update_event(self, event_id=None):
        """This endpoint updates a specific event"""
        data = await request.get_json()
        requester = get_jwt_identity()
        if not data:
             status_code = HTTPStatus.BAD_REQUEST
             return jsonify(message="Request body is required.", status=status_code.phrase), status_code
        try:
            if event_id:
                event_info = await self.conn.fetch(event_id)
                if not event_info:
                    status_code = HTTPStatus.NOT_FOUND
                    return jsonify(message="Event not found", status=status_code.phrase), status_code
                
                if event_info['creator'] == requester:
                    if result := await self.conn.update_event_data(event_id, data):
                        status_code = HTTPStatus.OK
                        return jsonify(data=result, message="Event updated successfully.", status=status_code.phrase), status_code
                else:
                    status_code = HTTPStatus.FORBIDDEN
                    return jsonify(message="Unauthorized attempt", status=status_code.phrase), status_code
            else:
                 status_code = HTTPStatus.BAD_REQUEST
                 return jsonify(message="Event ID is required in the path.", status=status_code.phrase), status_code
        except Exception as e:
            app.logger.error(f"Error updating event {event_id}: {str(e)}", exc_info=True)
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return jsonify(message=f"Failed to update event: {str(e)}", status=status_code.phrase), status_code


    @route("/events", methods=["POST"])
    @jwt_required
    async def create_event(self):
        """Create an event"""
        try:
            form = await request.form
            files = await request.files
            data = form.to_dict()
            
            # Validate required fields
            required_fields = ["title", "description", "location", "time", "coordinates"]
            missing_fields = [field for field in required_fields if not data.get(field)]
            if missing_fields:
                status_code = HTTPStatus.BAD_REQUEST
                return jsonify(message=f"Missing required fields: {', '.join(missing_fields)}", status=status_code.phrase), status_code
            
            media_links = []
            data["event_id"] = (
                (RecordID("events", str(ruuid.uuid4()).split("-")[-1]))
                if not data.get("id", None)
                else RecordID("events", data["id"])
            )
            data["coordinates"] = form.getlist("coordinates[]", type=decimal.Decimal)
            if len(data["coordinates"]) == 1:
                # Probably only one coordinate provided, monkey patch
                data["coordinates"] += [decimal.Decimal(77.3299)]
                
            data["categories"] = form.getlist("categories[]")
            data["host"] = get_jwt_identity()
            data["creator"] = get_jwt_identity()
            data["filenames"] = [
                f"events/{data['host']}/{data['event_id'].id}/{file.filename}"
                for file in files.values()
            ]
            data["types"] = [file.content_type for file in files.values()]

            data["degree_of_freedom"] = form.get("degree_of_freedom", 1, type=int)

            data["time"] = datetime.fromisoformat(
                form.get("time", type=str).replace("Z", "+00:00")
            )

            data["is_private"] = (
                form.get("is_private", "false") == "true"
            )  # Default to False if not specified

            for i, file in enumerate(files.values()):
                data["filename"] = data["filenames"][i]
                data["type"] = data["types"][i]
                app.logger.warning(
                    f"Uploading new event media to GCP: {data['filename']}"
                )
                await app.RMQ._publish_media(data, file)

            app.logger.debug(f"Creating event data: {data}")
            if result := await self.conn.create_event(
                data
            ):  # Pass the raw data to the database method
                status_code = HTTPStatus.CREATED
                return jsonify(data=result, message="Event created successfully.", status=status_code.phrase), status_code

            app.logger.error("Failed to create event in DB")
            status_code = HTTPStatus.BAD_REQUEST
            return jsonify(message="Failed to create event", status=status_code.phrase), status_code
        except Exception as e:
            app.logger.error(f"Error creating event: {str(e)}", exc_info=True)
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return jsonify(message=f"Failed to create event: {str(e)}", status=status_code.phrase), status_code

    @route("/events/<event_id>/delete", methods=["DELETE"]) # Changed route slightly for consistency
    @jwt_required
    async def delete_event(self, event_id: str):
        """Delete an event"""
        try:
            # Add check if user is authorized to delete (e.g., is the host)
            user_id = get_jwt_identity()
            event = await self.conn.fetch(event_id)
            if not event:
                 status_code = HTTPStatus.NOT_FOUND
                 return jsonify(message="Event not found", status=status_code.phrase), status_code
            if event.get("host") != user_id: # Assuming host field stores user ID
                 status_code = HTTPStatus.FORBIDDEN
                 return jsonify(message="Unauthorized to delete this event", status=status_code.phrase), status_code

            await self.conn.delete_event(event_id)
            status_code = HTTPStatus.NO_CONTENT
            return jsonify(message="Event deleted successfully", status=status_code.phrase), status_code
        except Exception as e:
            app.logger.error(f"Error deleting event {event_id}: {str(e)}", exc_info=True)
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return jsonify(message=f"Failed to delete event: {str(e)}", status=status_code.phrase), status_code

    @route("/events/private", methods=["GET"])
    @jwt_required
    async def fetch_private_events(self):
        """This endpoints returns the private events"""
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 20))
        try:
            result = await self.conn.fetch_private(page, limit)
            status_code = HTTPStatus.OK
            return jsonify(data=result, message="Private events fetched successfully.", status=status_code.phrase), status_code
        except Exception as e:
            app.logger.error(f"Error fetching private events: {str(e)}", exc_info=True)
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return jsonify(message=f"Failed to fetch private events: {str(e)}", status=status_code.phrase), status_code
        
    
    
    @route("/events/public", methods=["GET"])
    @jwt_required
    async def fetch_public_events(self):
        """This endpoints returns public events"""
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 20))
        try:
            result = await self.conn.fetch_all(page, limit)
            status_code = HTTPStatus.OK
            return jsonify(data=result, message="Public events fetched successfully.", status=status_code.phrase), status_code
        except Exception as e:
            app.logger.error(f"Error fetching public events: {str(e)}", exc_info=True)
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return jsonify(message=f"Failed to fetch public events: {str(e)}", status=status_code.phrase), status_code


    @route("/events/distance", methods=["GET"])
    @jwt_required
    async def fetch_by_distance(self):
        """Fetch a list of events by distance."""
        try:
            location = (
                float(request.args.get("lat", 0)),
                float(request.args.get("lng", 0)),
            )
            distance = int(request.args.get("distance", 1000))
            result = await self.conn.fetch_by_distance(location, distance)
            status_code = HTTPStatus.OK
            return jsonify(data=result, message="Events fetched by distance successfully.", status=status_code.phrase), status_code
        except ValueError:
             status_code = HTTPStatus.BAD_REQUEST
             return jsonify(message="Invalid latitude, longitude, or distance parameters.", status=status_code.phrase), status_code
        except Exception as e:
            app.logger.error(f"Error fetching events by distance: {str(e)}", exc_info=True)
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return jsonify(message=f"Failed to fetch events by distance: {str(e)}", status=status_code.phrase), status_code


    @route("/events/<event_id>/status", methods=["PATCH"])
    @jwt_required
    async def update_event_status(self, event_id: str):
        """Update event status"""
        try:
            user_id = get_jwt_identity()
            data = await request.get_json()
            new_status = data.get("status")

            if not new_status:
                status_code = HTTPStatus.BAD_REQUEST
                return jsonify(message="Status is required in request body.", status=status_code.phrase), status_code

            # Verify user has permission to update this event
            event = await self.conn.fetch(event_id)
            app.logger.info(f"Updating event {event_id} status to '{new_status}' by user {user_id}")
            if not event:
                app.logger.warning(f"Event not found: {event_id}")
                status_code = HTTPStatus.NOT_FOUND
                return jsonify(message="Event not found", status=status_code.phrase), status_code

            if event.get("host") != user_id: # Assuming host field stores user ID
                app.logger.warning(
                    f"Unauthorized access attempt to event {event_id} by user {user_id}"
                )
                status_code = HTTPStatus.FORBIDDEN
                return jsonify(message="Unauthorized to update this event", status=status_code.phrase), status_code

            result = await self.conn.update_event_status(
                event_id, status=new_status, metadata=data.get("metadata")
            )
            app.logger.info(f"Successfully updated status for event {event_id}")
            status_code = HTTPStatus.OK
            return jsonify(data=result, message="Event status updated successfully.", status=status_code.phrase), status_code
        except ValueError as ve: # Catch specific validation errors from connector
             status_code = HTTPStatus.BAD_REQUEST
             return jsonify(message=str(ve), status=status_code.phrase), status_code
        except Exception as e:
            app.logger.error(
                f"Error updating event status for {event_id}: {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return jsonify(message=f"Failed to update event status: {str(e)}", status=status_code.phrase), status_code

    @route("/events/<event_id>/live", methods=["GET"])
    @jwt_required
    async def start_event_live_updates(self, event_id: str):
        """Start live updates for an event"""
        try:
            user_id = get_jwt_identity()

            # Verify user has access to this event
            event = await self.conn.fetch(event_id)
            app.logger.info(
                f"Starting live updates for event {event_id} by user {user_id}"
            )
            if not event:
                app.logger.warning(f"Event not found: {event_id}")
                status_code = HTTPStatus.NOT_FOUND
                return jsonify(message="Event not found", status=status_code.phrase), status_code

            if event.get("host") != user_id: # Assuming host field stores user ID
                app.logger.warning(
                    f"Unauthorized live updates access attempt for event {event_id} by user {user_id}"
                )
                status_code = HTTPStatus.FORBIDDEN
                return jsonify(message="Unauthorized to start live updates for this event", status=status_code.phrase), status_code

            # Check if live query already exists
            existing_live_id = await self._get_live_query(event_id)
            if existing_live_id:
                app.logger.info(f"Returning existing live query for event {event_id}")
                status_code = HTTPStatus.OK
                return jsonify(data={"live_query_id": existing_live_id}, message="Live updates already running.", status=status_code.phrase), status_code

            # Start the live query and get its ID
            live_id = await self.conn.live_query(event_id)
            if not live_id: # Handle potential failure in starting live query
                 app.logger.error(f"Failed to obtain live_id for event {event_id} from connector")
                 status_code = HTTPStatus.INTERNAL_SERVER_ERROR
                 return jsonify(message="Failed to start live updates.", status=status_code.phrase), status_code


            # Store in Redis
            await self._store_live_query(event_id, live_id)

            app.logger.info(f"Started new live query for event {event_id}")
            status_code = HTTPStatus.OK
            return jsonify(data={"live_query_id": live_id}, message="Live updates started successfully.", status=status_code.phrase), status_code

        except Exception as e:
            app.logger.error(
                f"Failed to start live query for event {event_id}: {str(e)}",
                exc_info=True,
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return jsonify(message=f"Failed to start live updates: {str(e)}", status=status_code.phrase), status_code

    @route("/events/<event_id>/live", methods=["DELETE"])
    @jwt_required
    async def stop_event_live_updates(self, event_id: str):
        """Stop live updates for an event"""
        try:
            user_id = get_jwt_identity()

            # Verify user has access to this event
            event = await self.conn.fetch(event_id)
            app.logger.info(
                f"Stopping live updates for event {event_id} by user {user_id}"
            )
            if not event:
                app.logger.warning(f"Event not found: {event_id}")
                status_code = HTTPStatus.NOT_FOUND
                return jsonify(message="Event not found", status=status_code.phrase), status_code

            # Use .get() with default for safer access if host might be missing
            if event.get("host") != user_id:
                app.logger.warning(
                    f"Unauthorized attempt to stop live updates for event {event_id} by user {user_id}"
                )
                status_code = HTTPStatus.FORBIDDEN
                return jsonify(message="Unauthorized to stop live updates for this event", status=status_code.phrase), status_code

            # Get live query ID from Redis
            live_id = await self._get_live_query(event_id)
            if live_id:
                await self.conn.kill_live_query(live_id)
                await self._remove_live_query(event_id)
                app.logger.info(
                    f"Successfully stopped live updates for event {event_id}"
                )
                status_code = HTTPStatus.NO_CONTENT
                return jsonify(message="Live updates stopped successfully.", status=status_code.phrase), status_code

            app.logger.info(f"No live updates running for event {event_id}")
            status_code = HTTPStatus.OK # Or NO_CONTENT if preferred
            return jsonify(message="No live updates running for this event.", status=status_code.phrase), status_code # Or NO_CONTENT if preferred

        except Exception as e:
            app.logger.error(
                f"Failed to stop live query for event {event_id}: {str(e)}",
                exc_info=True,
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return jsonify(message=f"Failed to stop live updates: {str(e)}", status=status_code.phrase), status_code

    @route("/events/<event_id>/buy_ticket", methods=["POST"])
    @jwt_required
    async def buy_ticket(self, event_id: str):
        """Buy a ticket for an event"""
        try:
            user_id = get_jwt_identity()

            # Verify the event exists
            event = await self.conn.fetch(event_id)
            if not event:
                status_code = HTTPStatus.NOT_FOUND
                return jsonify(message="Event not found", status=status_code.phrase), status_code

            # Create the attendance relationship
            attendance_data = {
                "user": user_id,
                "event": event_id,
                "status": "confirmed",  # You can add more fields as needed
            }

            # Assuming you have a method to create the relationship in your database
            await self.conn.create_attendance(attendance_data)

            status_code = HTTPStatus.CREATED
            return jsonify(message="Ticket purchased successfully", status=status_code.phrase), status_code

        except Exception as e:
            app.logger.error(
                f"Error buying ticket for event {event_id}: {str(e)}", exc_info=True
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return jsonify(message=f"Failed to buy ticket: {str(e)}", status=status_code.phrase), status_code
