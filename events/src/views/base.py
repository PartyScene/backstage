import datetime
import random
import json
import asyncio
from typing import AsyncGenerator, Dict, Any, Tuple
from http import HTTPStatus

from dataclasses import dataclass
from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify, websocket
from quart_schema import validate_request, DataSource

from ..connectors import EventsDB
from ..schema import Events
from classful import route, QuartClassful

from quart_jwt_extended import jwt_required, get_jwt_identity


class BaseView(QuartClassful):
    app = app

    def __init__(self):
        self.db: EventsDB = app.db
        self.redis = app.redis_handler.get_connection()

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

    @route("/create", methods=["POST"])
    @jwt_required
    @validate_request(Events)
    async def create_event(self, event: Events):
        """Create an event"""
        result = await self.db.create(event)
        return result, 201
    
    @route("/events/all", methods=["GET"])
    @jwt_required
    async def fetch_all(self):
        """This endpoints returns all the events"""
        result = await self.db.fetch_all()
        return result, 200
    
    @route("/events/location", methods=["GET"])
    @jwt_required
    async def fetch_by_location(self):
        """Fetch a list of events by location. If the `nearby` endpoint is called, then...

        Returns:
            array : List of events
        """
        location = (
            float(request.args.get('lat')),
            float(request.args.get('long'))
        )
        distance = int(request.args.get('distance'))
        result = await self.db.fetch_by_distance(location, distance)
        return result, 200

    @route("/events/<event_id>/status", methods=["PATCH"])
    @jwt_required
    async def update_event_status(self, event_id: str) -> Tuple[Dict[str, Any], int]:
        """Update event status"""
        try:
            user_id = get_jwt_identity()
            data = await request.get_json()
            
            # Verify user has permission to update this event
            event = await self.db.fetch(event_id)
            if not event or event['host']['id'] != user_id:
                return {"error": "Unauthorized"}, HTTPStatus.FORBIDDEN
            
            result = await self.db.update_event_status(
                event_id,
                status=data['status'],
                metadata=data.get('metadata')
            )
            return result, HTTPStatus.OK
        except Exception as e:
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/events/<event_id>/live", methods=["GET"])
    @jwt_required
    async def start_event_live_updates(self, event_id: str):
        """Start live updates for an event"""
        try:
            user_id = get_jwt_identity()
            
            # Verify user has access to this event
            event = await self.db.fetch(event_id)
            if not event or (
                event['host']['id'] != user_id and 
                user_id not in [a['id'] for a in event.get('attendees', [])]
            ):
                return {"error": "Unauthorized"}, HTTPStatus.FORBIDDEN

            # Check if live query already exists
            existing_live_id = await self._get_live_query(event_id)
            if existing_live_id:
                return {"live_query_id": existing_live_id}, HTTPStatus.OK

            # Start the live query and get its ID
            live_id = await self.db.live_query(event_id)
            
            # Store in Redis
            await self._store_live_query(event_id, live_id)
            
            return {"live_query_id": live_id}, HTTPStatus.OK

        except Exception as e:
            app.logging.error(f"Failed to start live query: {str(e)}")
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR

    @route("/events/<event_id>/live", methods=["DELETE"])
    @jwt_required
    async def stop_event_live_updates(self, event_id: str):
        """Stop live updates for an event"""
        try:
            user_id = get_jwt_identity()
            
            # Verify user has access to this event
            event = await self.db.fetch(event_id)
            if not event or event['host']['id'] != user_id:
                return {"error": "Unauthorized"}, HTTPStatus.FORBIDDEN

            # Get live query ID from Redis
            live_id = await self._get_live_query(event_id)
            if live_id:
                await self.db.kill_live_query(live_id)
                await self._remove_live_query(event_id)
                return {"message": "Live updates stopped"}, HTTPStatus.OK
            
            return {"message": "No live updates running"}, HTTPStatus.OK

        except Exception as e:
            app.logging.error(f"Failed to stop live query: {str(e)}")
            return {"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR
