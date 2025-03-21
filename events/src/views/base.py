from datetime import datetime
import random
import json
import asyncio
from typing import AsyncGenerator, Dict, Any, Tuple, Optional
from http import HTTPStatus

from dataclasses import dataclass
from pprint import pprint
from quart import (
    make_response,
    render_template,
    current_app as app,
    request,
    jsonify,
    websocket,
)
from quart_schema import validate_request, DataSource

from ..connectors import EventsDB
from shared.classful import route, QuartClassful

from quart_jwt_extended import jwt_required, get_jwt_identity
from aiocache import cached


class BaseView(QuartClassful):

    def __init__(self):
        self.conn: EventsDB = app.conn
        self.redis = app.redis
        app.logger = app.logger

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

        # Check database connection
        try:
            db_info = await self.conn._info()
            health_status["dependencies"]["database"] = "healthy"
        except Exception as e:
            app.logger.error(f"Database health check failed: {e}")
            health_status["dependencies"]["database"] = "unhealthy"
            health_status["status"] = "degraded"

        # Check Redis connection
        try:
            redis_ping = await self.redis.ping()
            health_status["dependencies"]["redis"] = (
                "healthy" if redis_ping else "unhealthy"
            )
            if not redis_ping:
                health_status["status"] = "degraded"
        except Exception as e:
            app.logger.error(f"Redis health check failed: {e}")
            health_status["dependencies"]["redis"] = "unhealthy"
            health_status["status"] = "degraded"

        status_code = (
            HTTPStatus.OK
            if health_status["status"] == "healthy"
            else HTTPStatus.SERVICE_UNAVAILABLE
        )

        return jsonify(health_status), status_code

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

        if event_id:
            if result := await self.conn.fetch(event_id):
                return result, HTTPStatus.OK
            return {"error": "Event not found"}, HTTPStatus.NOT_FOUND

        if any([x in request.args for x in ("lat", "lng")]):
            # They requested for Lat Lng soo
            location = (
                float(request.args.get("lat", 0)),
                float(request.args.get("lng", 0)),
            )
            distance = int(request.args.get("distance", 1000))
            result = await self.conn.fetch_by_distance(location, distance)
            return result, HTTPStatus.OK

        result = await self.conn.fetch_all(page, limit)
        return result, HTTPStatus.OK

    @route("/events/<event_id>", methods=["PATCH"])
    @jwt_required
    async def update_event(self, event_id=None):
        """This endpoints returns all the events"""
        data = await request.get_json()
        if event_id:
            if result := await self.conn.update_event_data(event_id, data):
                return result, HTTPStatus.OK
            return {"error": "Event not found"}, HTTPStatus.NOT_FOUND

    @route("/events", methods=["POST"])
    @jwt_required
    async def create_event(self):
        """Create an event"""
        try:
            data = await request.get_json()  # Get raw JSON data
            # You can add your own validation here if needed
            data["host"] = data.get("host", get_jwt_identity())
            if result := await self.conn.create_event(
                data
            ):  # Pass the raw data to the database method
                return jsonify(result), HTTPStatus.CREATED
            return {"error": "Bad params"}, HTTPStatus.BAD_REQUEST
        except Exception as e:
            app.logger.error(f"Error creating event: {str(e)}", exc_info=True)
            return {"error": str(e)}, HTTPStatus.BAD_REQUEST

    @route("/events/<event_id>/delete", methods=["DELETE"])
    @jwt_required
    async def delete_event(self, event_id: str):
        """Delete an event"""
        try:
            await self.conn.delete_event(event_id)
            return {"message": "Event deleted successfully"}, HTTPStatus.NO_CONTENT
        except Exception as e:
            app.logger.error(f"Error deleting event: {str(e)}", exc_info=True)
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/events/public", methods=["GET"])
    async def fetch_public_events(self):
        """This endpoints returns all the public events"""
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 20))
        result = await self.conn.fetch_all_public(page, limit)
        return result, HTTPStatus.OK

    @route("/events/distance", methods=["GET"])
    @jwt_required
    async def fetch_by_distance(self):
        """Fetch a list of events by distance. If the `nearby` endpoint is called, then...

        Returns:
            array : List of events
        """
        location = (
            float(request.args.get("lat", 0)),
            float(request.args.get("lng", 0)),
        )
        distance = int(request.args.get("distance", 1000))
        result = await self.conn.fetch_by_distance(location, distance)
        return result, HTTPStatus.OK

    @route("/events/<event_id>/status", methods=["PATCH"])
    @jwt_required
    async def update_event_status(self, event_id: str) -> Tuple[Dict[str, Any], int]:
        """Update event status"""
        try:
            user_id = get_jwt_identity()
            data = await request.get_json()

            # Verify user has permission to update this event
            event = await self.conn.fetch(event_id)
            app.logger.info(f"Updating event {event_id} by user {user_id}")
            if not event:
                app.logger.warning(f"Event not found: {event_id}")
                return {"error": "Event not found"}, HTTPStatus.NOT_FOUND

            if event["host"] != user_id:
                app.logger.warning(
                    f"Unauthorized access attempt to event {event_id} by user {user_id}"
                )
                return {"error": "Unauthorized"}, HTTPStatus.FORBIDDEN

            result = await self.conn.update_event_status(
                event_id, status=data["status"], metadata=data.get("metadata")
            )
            app.logger.info(f"Successfully updated status for event {event_id}")
            return result, HTTPStatus.OK
        except Exception as e:
            app.logger.error(
                f"Error updating event status for {event_id}: {str(e)}", exc_info=True
            )
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

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
                return {"error": "Event not found"}, HTTPStatus.NOT_FOUND

            if event["host"] != user_id:
                app.logger.warning(
                    f"Unauthorized live updates access attempt for event {event_id} by user {user_id}"
                )
                return {"error": "Unauthorized"}, HTTPStatus.FORBIDDEN

            # Check if live query already exists
            existing_live_id = await self._get_live_query(event_id)
            if existing_live_id:
                app.logger.info(f"Returning existing live query for event {event_id}")
                return {"live_query_id": existing_live_id}, HTTPStatus.OK

            # Start the live query and get its ID
            live_id = await self.conn.live_query(event_id)

            # Store in Redis
            await self._store_live_query(event_id, live_id)

            app.logger.info(f"Started new live query for event {event_id}")
            return {"live_query_id": live_id}, HTTPStatus.OK

        except Exception as e:
            app.logger.error(
                f"Failed to start live query for event {event_id}: {str(e)}",
                exc_info=True,
            )
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

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
                return {"error": "Event not found"}, HTTPStatus.NOT_FOUND

            if event["host"].id != user_id:
                app.logger.warning(
                    f"Unauthorized attempt to stop live updates for event {event_id} by user {user_id}"
                )
                return {"error": "Unauthorized"}, HTTPStatus.FORBIDDEN

            # Get live query ID from Redis
            live_id = await self._get_live_query(event_id)
            if live_id:
                await self.conn.kill_live_query(live_id)
                await self._remove_live_query(event_id)
                app.logger.info(
                    f"Successfully stopped live updates for event {event_id}"
                )
                return {"message": "Live updates stopped"}, HTTPStatus.NO_CONTENT

            app.logger.info(f"No live updates running for event {event_id}")
            return {"message": "No live updates running"}, HTTPStatus.NO_CONTENT

        except Exception as e:
            app.logger.error(
                f"Failed to stop live query for event {event_id}: {str(e)}",
                exc_info=True,
            )
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/events/<event_id>/buy_ticket", methods=["POST"])
    @jwt_required
    async def buy_ticket(self, event_id: str):
        """Buy a ticket for an event"""
        try:
            user_id = get_jwt_identity()

            # Verify the event exists
            event = await self.conn.fetch(event_id)
            if not event:
                return {"error": "Event not found"}, HTTPStatus.NOT_FOUND

            # Create the attendance relationship
            attendance_data = {
                "user": user_id,
                "event": event_id,
                "status": "confirmed",  # You can add more fields as needed
            }

            # Assuming you have a method to create the relationship in your database
            await self.conn.create_attendance(attendance_data)

            return {"message": "Ticket purchased successfully"}, HTTPStatus.CREATED

        except Exception as e:
            app.logger.error(
                f"Error buying ticket for event {event_id}: {str(e)}", exc_info=True
            )
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR
