from datetime import datetime
import random
import orjson as json
import asyncio
import os
import uuid

from typing import AsyncGenerator, Dict, Any, Tuple, Optional
from http import HTTPStatus
from shared.utils import recursively_sign_object_media, sign_media_object, api_response, api_error, record_id_to_json

from shared.middleware.validation import ValidationMiddleware

from dataclasses import dataclass
from pprint import pprint
from quart import (
    Response,
    make_response,
    render_template,
    current_app as app,
    request,
    websocket,
)
from events.src.connectors import EventsDB
from shared.classful import route, QuartClassful
from shared.kpi import BusinessMetrics
from shared.workers.novu import NotificationManager
from shared.workers.novu.recap import collect_recap

from quart_jwt_extended import jwt_required, get_jwt_identity
from aiocache import cached

from shared.workers.rmq import RMQBroker
import uuid_utils as ruuid

from surrealdb import RecordID, Duration

# Stream Video client — for granting/revoking the attendee streaming role
from getstream import Stream as _Stream
from getstream.models import MemberRequest as _MemberRequest
_STREAM_API_KEY    = os.environ.get("STREAM_API_KEY", "")
_STREAM_API_SECRET = os.environ.get("STREAM_API_SECRET", "")
_stream_video      = _Stream(api_key=_STREAM_API_KEY, api_secret=_STREAM_API_SECRET, timeout=10.0)
from surrealdb.data import GeometryPoint


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
        
    async def check_ticket_verify_authorization(
        self, event_id: str, user_id: str
    ) -> bool:
        """
        Check if a user is authorized to verify tickets for
        an event. Returns (authorized).

        A user is authorized if they are the host OR an assigned collector.
        """
        async with self.pool.acquire() as conn:
            await conn.let("event", RecordID("events", event_id))
            await conn.let("user",  RecordID("users",  user_id))

            response = await conn.query_raw(
                """
                LET $ev = SELECT host FROM ONLY $event;
                IF $ev = NONE {
                    THROW "event_not_found";
                };
                LET $is_host = $ev.host = $user;
                LET $is_collector = count(
                    SELECT id FROM event_collectors
                    WHERE in = $event AND out = $user
                ) > 0;
                RETURN {
                    authorized:       $is_host OR $is_collector,
                };
                """
            )

        stmts = response.get("result", [])
        for s in stmts:
            if isinstance(s, dict) and s.get("status") == "ERR":
                err = s.get("result", "")
                if "event_not_found" in err:
                    raise ValueError("Event not found")
                raise Exception(f"check_terminal_authorization failed: {err}")

        payload = stmts[-1]["result"]
        return payload["authorized"]



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

        return api_response(message, status_code, data=health_status)

    @route("/events/<event_id>/attend", methods=["POST"])
    @jwt_required
    async def mark_attendance(self, event_id: str):
        """Mark attendance for an event"""
        try:
            user_id = get_jwt_identity()

            event = await self.conn.fetch(event_id)
            if not event:
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            # Create the attendance relationship
            attendance_data = {
                "user": user_id,
                "event": event_id,
                "status": "confirmed",  # You can add more fields as needed
            }

            result = await self.conn.create_attendance(attendance_data)
            BusinessMetrics.EVENT_ATTENDANCES.inc()

            # Fire RSVP notifications without blocking the response
            asyncio.ensure_future(
                self._send_rsvp_notifications(user_id, event_id, event)
            )

            return api_response(
                "Attendance confirmed",
                HTTPStatus.OK,
                data=result,
            )

        except Exception as e:
            app.logger.error(
                f"Error buying ticket for event {event_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to buy ticket: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/<event_id>", methods=["GET"])
    @jwt_required
    async def fetch_event(self, event_id):
        """This endpoints returns a specific event"""
        return await self.fetch_events(event_id)

    @route("/events/<event_id>/report", methods=["POST"])
    @jwt_required
    async def report_event(self, event_id):
        """This endpoints reports a specific event"""
        reporter = get_jwt_identity()
        data = await request.get_json()
        reason = data.get("reason", "")
        if not reason:
            return api_error("Reason is required", HTTPStatus.BAD_REQUEST)

        # Check if the event exists

        event_info = await self.conn.fetch(event_id)
        if not event_info:
            return api_error("Event not found", HTTPStatus.NOT_FOUND)

        if result := await self.conn._report_resource(
            {"reason": reason, "reporter": reporter, "resource": event_info["id"]}
        ):
            return api_response(
                "Resource reported",
                HTTPStatus.CREATED,
                data=result,
            )

    @route("/events", methods=["GET"])
    async def fetch_events(self, event_id=None):
        """This endpoints returns all the events"""
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 20))

        try:
            if event_id:
                if result := await self.conn.fetch(event_id):
                    status_code = HTTPStatus.OK
                    # Check if the event has media and sign it
                    try:
                        result = await recursively_sign_object_media(result)
                        result['event']['host'] = await recursively_sign_object_media(result['event']['host'])
                    except Exception as e:
                        app.logger.warning(f"Failed to sign media URLS: {str(e)}")
                        # continue
                    return api_response(
                        "Event fetched successfully.",
                        HTTPStatus.OK,
                        data=result,
                    )
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            if any([x in request.args for x in ("lat", "lng")]):
                # They requested for Lat Lng soo
                try:
                    location = (
                        float(request.args.get("lat", 0)),
                        float(request.args.get("lng", 0)),
                    )
                    distance = int(request.args.get("distance", 1000))
                except ValueError:
                    return api_error(
                        "Invalid latitude, longitude, or distance parameters.",
                        HTTPStatus.BAD_REQUEST
                    )

                result = await self.conn.fetch_by_distance(location, distance)
                result = await recursively_sign_object_media(result)
                for event in result:
                    event['event']['host'] = await recursively_sign_object_media(event['event']['host'])

                return api_response(
                    "Events fetched by distance successfully.",
                    HTTPStatus.OK,
                    data=result,
                )

            # Use trending-ranked results for the public discover feed.
            # fn::fetch_trending_events scores by (attendee_count × 3 + post_count × 2)
            # so events with momentum surface first instead of newest-created.
            result = await self.conn.fetch_trending_events(page, limit)
            result = await recursively_sign_object_media(result)
            for event in result:
                event["event"]["host"] = await recursively_sign_object_media(event['event']['host'])
            return api_response(
                "Events fetched successfully.",
                HTTPStatus.OK,
                data=result,
            )
        except Exception as e:
            app.logger.error(f"Error fetching events: {str(e)}", exc_info=True)
            return api_error(
                f"Failed to fetch events: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/<event_id>", methods=["PATCH"])
    @jwt_required
    async def update_event(self, event_id=None):
        """This endpoint updates a specific event"""
        data = await request.get_json()
        requester = get_jwt_identity()
        if not data:
            return api_error("Request body is required.", HTTPStatus.BAD_REQUEST)
        try:
            # Format fields to match DB schema (same transforms as create_event)
            if "time" in data:
                data["time"] = datetime.fromisoformat(
                    data["time"].replace("Z", "+00:00")
                )

            if "duration" in data:
                data["duration"] = Duration.parse(data["duration"]).minutes

            if "coordinates" in data:
                coords = tuple(float(x) for x in data.pop("coordinates"))
                data["location"] = {
                    "address": data.get("location", ""),
                    "coordinates": GeometryPoint.parse_coordinates(coords),
                }
            elif "location" in data:
                data["location"] = {
                    "address": data["location"],
                }

            if "is_private" in data and isinstance(data["is_private"], str):
                data["is_private"] = data["is_private"] == "true"

            if "is_free" in data and isinstance(data["is_free"], str):
                data["is_free"] = data["is_free"] == "true"

            if event_id:
                event_info = await self.conn.fetch(event_id)
                if not event_info:
                    return api_error("Event not found", HTTPStatus.NOT_FOUND)

                if event_info["creator"] == requester:
                    if result := await self.conn.update_event_data(event_id, data):
                        material_changes = [
                            f for f in ("time", "location", "coordinates")
                            if f in data
                        ]
                        if material_changes:
                            event_name = event_info.get("title") or event_info.get("name") or "your event"
                            asyncio.ensure_future(
                                self._notify_event_updated(
                                    event_id, event_name, material_changes
                                )
                            )
                        return api_response(
                            "Event updated successfully.",
                            HTTPStatus.OK,
                            data=result,
                        )
                else:
                    return api_error("Unauthorized attempt", HTTPStatus.FORBIDDEN)
            else:
                return api_error("Event ID is required in the path.", HTTPStatus.BAD_REQUEST)
        except Exception as e:
            app.logger.error(
                f"Error updating event {event_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to update event: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events", methods=["POST"])
    @ValidationMiddleware.validate_file_upload(
        max_size=50 * 1024 * 1024,
        required=True
    )
    @jwt_required
    async def create_event(self):
        """Create an event"""
        try:
            form = await request.form
            files = await request.files
            
            data = form.to_dict().copy()

            # Validate required fields
            required_fields = [
                "title",
                "description",
                "location",
                "time",
                "coordinates[]",
                "price",
            ]
            # missing_fields = any( [field not in data for])
            missing_fields = [field for field in required_fields if not field in data]
            if missing_fields:
                return api_error(
                    f"Missing required fields: {', '.join(missing_fields)}",
                    HTTPStatus.BAD_REQUEST
                )

            media_links = []
            # Always generate a new UUID for event creation, never trust client-provided IDs
            data.pop("id", None)  # Remove any stale ID from client
            data["event_id"] = RecordID("events", str(ruuid.uuid4()).split("-")[-1])
            
            data["coordinates"] = form.getlist("coordinates[]", type=float)
            if len(data["coordinates"]) == 1:
                # Probably only one coordinate provided, monkey patch
                data["coordinates"] += [77.3299]

            data["categories"] = form.getlist("categories[]")
            data["host"] = get_jwt_identity()
            data["creator"] = get_jwt_identity()

            # filename flow
            data["filenames"] = [
                f"events/{data['host']}/{data['event_id'].id}/{str(ruuid.uuid4()).split('-')[-1]}{os.path.splitext(file.filename)[-1]}"
                for file in files.values()
            ]
            data["types"] = [file.content_type for file in files.values()]

            data["degree_of_freedom"] = form.get("degree_of_freedom", 1, type=int)
            data["price"] = form.get("price", type=float)
            data["time"] = datetime.fromisoformat(
                form.get("time", "", type=str).replace("Z", "+00:00")
            )

            data["is_private"] = (
                form.get("is_private", "false") == "true"
            )  # Default to False if not specified

            data["is_free"] = (
                form.get("is_free", "false") == "true"
            )  # Default to False if not specified

            # Handle duration if provided (e.g., "2h", "1h30m", "45m")
            if duration_str := form.get("duration", type=str):
                data["duration"] = Duration.parse(duration_str).minutes

            for i, file in enumerate(files.values()):
                # Create isolated data dict for each file to prevent race conditions
                file_data = {
                    "filename": data["filenames"][i],
                    "type": data["types"][i],
                    "host": data["host"],
                    "event_id": data["event_id"],
                    "creator": data["creator"],
                }
                app.logger.warning(
                    f"Uploading new event media to GCP: {file_data['filename']}"
                )
                await app.RMQ._publish_media(record_id_to_json(file_data), file)

            app.logger.debug(f"Creating event data: {data}")

            if result := await self.conn.create_event(
                data
            ):  # Pass the raw data to the database method
                BusinessMetrics.EVENTS_CREATED.inc()
                return api_response(
                    "Event created successfully.",
                    HTTPStatus.CREATED,
                    data=result,
                )

            app.logger.error("Failed to create event in DB")
            return api_error("Failed to create event", HTTPStatus.BAD_REQUEST)
        except Exception as e:
            app.logger.error(f"Error creating event: {str(e)}", exc_info=True)
            return api_error(
                f"Failed to create event: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/<event_id>/similar", methods=["GET"])
    @jwt_required
    async def fetch_similar_events(self, event_id: str):
        """
        Returns visually similar future events based on ViT-768 image embeddings.

        Query params:
            limit (int, optional): 1-20, default 10.

        Response 200:
            { "data": [{ "event": {...preview card...}, "visual_distance": float }] }
        """
        try:
            limit = min(int(request.args.get("limit", 10)), 20)
        except (ValueError, TypeError):
            return api_error("limit must be an integer.", HTTPStatus.BAD_REQUEST)

        try:
            event = await self.conn.fetch(event_id)
            if not event:
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            cache_key = f"similar_events:{event_id}:{limit}"
            import orjson as _json
            cached = await self.redis.get(cache_key)
            if cached:
                return api_response(
                    "Similar events fetched successfully.",
                    HTTPStatus.OK,
                    data=_json.loads(cached),
                )

            results = await self.conn.fetch_similar_events(event_id, limit)

            if not results:
                return api_response(
                    "No similar events found yet — more appear as media is processed.",
                    HTTPStatus.OK,
                    data=[],
                )

            for item in results:
                if item.get("event") and item["event"].get("media"):
                    item["event"]["media"] = await sign_media_object(item["event"]["media"])
                if item.get("event") and item["event"].get("host"):
                    item["event"]["host"] = await recursively_sign_object_media(item["event"]["host"])

            # Only cache non-empty results. An empty result usually means r18e
            # hasn't processed this event's media yet — caching it would serve
            # stale [] for 5 minutes even after embeddings become available.
            if results:
                await self.redis.setex(cache_key, 300, _json.dumps(results, default=str))

            return api_response(
                "Similar events fetched successfully.",
                HTTPStatus.OK,
                data=results,
            )

        except Exception as e:
            app.logger.error(
                f"Error fetching similar events for {event_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to fetch similar events: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @route(
        "/events/<event_id>", methods=["DELETE"]
    )  # Changed route slightly for consistency
    @jwt_required
    async def delete_event(self, event_id: str):
        """Delete an event"""
        try:
            # Add check if user is authorized to delete (e.g., is the host)
            user_id = get_jwt_identity()
            event = await self.conn.fetch(event_id)
            if not event:
                return api_error("Event not found", HTTPStatus.NOT_FOUND)
            if event.get("creator") != user_id:  # Assuming host field stores user ID
                return api_error("Unauthorized to delete this event", HTTPStatus.FORBIDDEN)

            event_name = event.get("title") or event.get("name") or "your event"
            await self.conn.delete_event(event_id)
            asyncio.ensure_future(
                self._notify_event_cancelled(event_id, event_name)
            )
            return api_response("Event deleted successfully", HTTPStatus.OK)
        except Exception as e:
            app.logger.error(
                f"Error deleting event {event_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to delete event: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/private", methods=["GET"])
    @jwt_required
    async def fetch_private_events(self):
        """This endpoints returns the private events"""
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 20))
        user = get_jwt_identity()
        try:
            result = await self.conn.fetch_private(user, page, limit)
            result = await recursively_sign_object_media(result)
            for event in result:
                event['event']['host'] = await recursively_sign_object_media(event['event']['host'])
            return api_response(
                "Private events fetched successfully.",
                HTTPStatus.OK,
                data=result,
            )
        except Exception as e:
            app.logger.error(f"Error fetching private events: {str(e)}", exc_info=True)
            return api_error(
                f"Failed to fetch private events: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/distance", methods=["GET"])
    @jwt_required
    async def fetch_by_distance(self):
        """Fetch a list of events by distance."""
        try:
            location = (
                float(request.args.get("lat", 0)),
                float(request.args.get("lng", 0)),
            )
            user = get_jwt_identity()
            distance = int(request.args.get("distance", 1000))
            result = await self.conn.fetch_by_distance(location, distance, user=user)
            result = await recursively_sign_object_media(result)
            for event in result:
                event['event']['host'] = await recursively_sign_object_media(event['event']['host'])

            return api_response(
                "Events fetched by distance successfully.",
                HTTPStatus.OK,
                data=result,
            )
        except ValueError:
            return api_error(
                "Invalid latitude, longitude, or distance parameters.",
                HTTPStatus.BAD_REQUEST
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching events by distance: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to fetch events by distance: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/<event_id>/status", methods=["PATCH"])
    @jwt_required
    async def update_event_status(self, event_id: str):
        """Update event status"""
        try:
            user_id = get_jwt_identity()
            data = await request.get_json()
            new_status = data.get("status")

            if not new_status:
                return api_error("Status is required in request body.", HTTPStatus.BAD_REQUEST)

            # Verify user has permission to update this event
            event = await self.conn.fetch(event_id)
            app.logger.info(
                f"Updating event {event_id} status to '{new_status}' by user {user_id}"
            )
            if not event:
                app.logger.warning(f"Event not found: {event_id}")
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            if event.get("creator") != user_id:  # Assuming host field stores user ID
                app.logger.warning(
                    f"Unauthorized access attempt to event {event_id} by user {user_id}"
                )
                return api_error("Unauthorized to update this event", HTTPStatus.FORBIDDEN)

            result = await self.conn.update_event_status(
                event_id, status=new_status, metadata=data.get("metadata")
            )
            app.logger.info(f"Successfully updated status for event {event_id}")

            # Fire recap notification to host when event ends
            if new_status == "ended":
                asyncio.ensure_future(
                    self._send_event_recap(event_id, event)
                )

            return api_response(
                "Event status updated successfully.",
                HTTPStatus.OK,
                data=result
            )
        except ValueError as ve:  # Catch specific validation errors from connector
            return api_error(str(ve), HTTPStatus.BAD_REQUEST)
        except Exception as e:
            app.logger.error(
                f"Error updating event status for {event_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to update event status: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    async def _send_event_recap(self, event_id: str, event: dict):
        """
        Collect post-event insights and send a PartyScene Wrapped
        recap to the host.  Runs as a background task so it never
        blocks the status-update response.
        """
        try:
            host = event.get("host") or event.get("creator") or ""
            if isinstance(host, dict):
                host_id = str(host.get("id", "")).split(":")[-1]
            else:
                host_id = str(host).split(":")[-1]

            if not host_id:
                app.logger.warning(
                    "Recap skipped for event %s: no host ID", event_id
                )
                return

            event_name = (
                event.get("title")
                or event.get("name")
                or "Your Event"
            )

            async with self.conn.pool.acquire() as conn:
                # Atomically claim so the CronJob won't send a duplicate
                claimed = await conn.query(
                    "UPDATE type::thing('events', $eid) "
                    "SET recap_sent = time::now() "
                    "WHERE recap_sent = NONE "
                    "RETURN BEFORE",
                    {"eid": event_id},
                )
                if not claimed:
                    app.logger.info(
                        "Recap already claimed for event %s", event_id
                    )
                    return

                recap_data = await collect_recap(conn, event_id)

            if not recap_data:
                app.logger.warning(
                    "Recap skipped for event %s: no data", event_id
                )
                return

            notifier = NotificationManager()
            await notifier.send_event_recap(
                host_subscriber_id=host_id,
                event_id=event_id,
                event_name=event_name,
                **recap_data,
            )
            app.logger.info(
                "Recap sent for event %s (%s)", event_id, event_name
            )
        except Exception as e:
            app.logger.error(
                "Recap dispatch failed for event %s: %s",
                event_id, e, exc_info=True,
            )

    async def _send_rsvp_notifications(
        self, user_id: str, event_id: str, event: dict
    ):
        """Fire attendee + host RSVP notifications in the background."""
        try:
            event_name = (
                event.get("title")
                or event.get("name")
                or "an event"
            )
            host = event.get("host") or {}
            host_id = host.get("id")

            # Fetch attendee name for the host notification
            attendee_name = "Someone"
            try:
                async with self.conn.pool.acquire() as conn:
                    user = await conn.query(
                        "SELECT first_name, last_name, username "
                        "FROM ONLY type::thing('users', $uid)",
                        {"uid": user_id},
                    )
                if user:
                    first = user.get("first_name", "")
                    last = user.get("last_name", "")
                    attendee_name = (
                        f"{first} {last}".strip()
                        or user.get("username", "Someone")
                    )
            except Exception:
                pass  # fall back to "Someone"

            notifier = NotificationManager()

            # Confirm to the attendee
            await notifier.send_event_rsvp_attendee(
                subscriber_id=user_id,
                event_name=event_name,
                event_id=event_id,
            )

            # Notify the host
            if host_id:
                await notifier.send_event_rsvp_host(
                    host_subscriber_id=host_id,
                    attendee_name=attendee_name,
                    event_name=event_name,
                    event_id=event_id,
                )
        except Exception as e:
            app.logger.error(
                "RSVP notification failed for event %s: %s",
                event_id, e, exc_info=True,
            )

    async def _notify_event_cancelled(self, event_id: str, event_name: str):
        """Fan out event-cancelled notifications to all ticket holders and RSVPs."""
        try:
            async with self.conn.pool.acquire() as conn:
                rows = await conn.query(
                    """
                    SELECT VALUE string::split(string::concat(user, ''), ':')[1]
                    FROM tickets
                    WHERE event = type::thing('events', $eid)
                    AND user != NONE
                    """,
                    {"eid": event_id},
                )
            attendee_ids = list({uid for uid in (rows or []) if uid})
            if not attendee_ids:
                return
            notifier = NotificationManager()
            await notifier.send_event_cancelled(
                attendee_ids=attendee_ids,
                event_name=event_name,
                event_id=event_id,
            )
            app.logger.info(
                "Event-cancelled notification sent for %s → %d attendees",
                event_id, len(attendee_ids),
            )
        except Exception as e:
            app.logger.error(
                "Event-cancelled notification failed for %s: %s",
                event_id, e, exc_info=True,
            )

    async def _notify_event_updated(
        self, event_id: str, event_name: str, changed_fields: list
    ):
        """Fan out event-updated notifications to all ticket holders."""
        try:
            async with self.conn.pool.acquire() as conn:
                rows = await conn.query(
                    """
                    SELECT VALUE string::split(string::concat(user, ''), ':')[1]
                    FROM tickets
                    WHERE event = type::thing('events', $eid)
                    AND user != NONE
                    """,
                    {"eid": event_id},
                )
            attendee_ids = list({uid for uid in (rows or []) if uid})
            if not attendee_ids:
                return
            notifier = NotificationManager()
            await notifier.send_event_updated(
                attendee_ids=attendee_ids,
                event_name=event_name,
                event_id=event_id,
                changed_fields=changed_fields,
            )
            app.logger.info(
                "Event-updated notification sent for %s → %d attendees, fields: %s",
                event_id, len(attendee_ids), changed_fields,
            )
        except Exception as e:
            app.logger.error(
                "Event-updated notification failed for %s: %s",
                event_id, e, exc_info=True,
            )

    async def _notify_guestlist_decision(
        self, guest_id: str, event_name: str, event_id: str, status: str
    ):
        """Notify a guest of the host's accept/decline decision."""
        try:
            notifier = NotificationManager()
            await notifier.send_guestlist_decision(
                guest_subscriber_id=guest_id,
                event_name=event_name,
                event_id=event_id,
                status=status,
            )
        except Exception as e:
            app.logger.error(
                "Guestlist-decision notification failed for guest %s event %s: %s",
                guest_id, event_id, e, exc_info=True,
            )

    async def _notify_guestlist_rsvp(
        self, host_id: str, guest_id: str, event_name: str, event_id: str, status: str
    ):
        """Notify the host when an invited guest accepts or declines."""
        try:
            guest_name = "A guest"
            try:
                async with self.conn.pool.acquire() as conn:
                    user = await conn.query(
                        "SELECT first_name, last_name, username "
                        "FROM ONLY type::thing('users', $uid)",
                        {"uid": guest_id},
                    )
                if user:
                    first = user.get("first_name", "")
                    last = user.get("last_name", "")
                    guest_name = (
                        f"{first} {last}".strip()
                        or user.get("username", "A guest")
                    )
            except Exception:
                pass
            notifier = NotificationManager()
            await notifier.send_guestlist_rsvp(
                host_subscriber_id=host_id,
                guest_name=guest_name,
                event_name=event_name,
                event_id=event_id,
                status=status,
            )
        except Exception as e:
            app.logger.error(
                "Guestlist-RSVP notification failed for host %s event %s: %s",
                host_id, event_id, e, exc_info=True,
            )

    async def _notify_ticket_checkin(
        self,
        host_id: str,
        event_name: str,
        event_id: str,
        attendee_name: str,
        ticket_number: str,
    ):
        """Notify the host of a fresh ticket check-in."""
        try:
            notifier = NotificationManager()
            await notifier.send_ticket_checkin_host(
                host_subscriber_id=host_id,
                event_name=event_name,
                event_id=event_id,
                attendee_name=attendee_name,
                ticket_number=ticket_number,
            )
        except Exception as e:
            app.logger.error(
                "Ticket-checkin notification failed for host %s event %s: %s",
                host_id, event_id, e, exc_info=True,
            )

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
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            if event.get("creator") != user_id:  # Assuming host field stores user ID
                app.logger.warning(
                    f"Unauthorized live updates access attempt for event {event_id} by user {user_id}"
                )
                return api_error(
                    "Unauthorized to start live updates for this event",
                    HTTPStatus.FORBIDDEN
                )

            # Check if live query already exists
            existing_live_id = await self._get_live_query(event_id)
            if existing_live_id:
                app.logger.info(f"Returning existing live query for event {event_id}")
                return api_response(
                    "Live updates already running.",
                    HTTPStatus.OK,
                    data={"live_query_id": existing_live_id}
                )

            # Start the live query and get its ID
            live_id = await self.conn.live_query(event_id)
            if not live_id:  # Handle potential failure in starting live query
                app.logger.error(
                    f"Failed to obtain live_id for event {event_id} from connector"
                )
                return api_error(
                    "Failed to start live updates.",
                    HTTPStatus.INTERNAL_SERVER_ERROR
                )

            # Store in Redis
            await self._store_live_query(event_id, live_id)

            app.logger.info(f"Started new live query for event {event_id}")
            return api_response(
                "Live updates started successfully.",
                HTTPStatus.OK,
                data={"live_query_id": live_id}
            )

        except Exception as e:
            app.logger.error(
                f"Failed to start live query for event {event_id}: {str(e)}",
                exc_info=True,
            )
            return api_error(
                f"Failed to start live updates: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

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
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            # Use .get() with default for safer access if host might be missing
            if event.get("creator") != user_id:
                app.logger.warning(
                    f"Unauthorized attempt to stop live updates for event {event_id} by user {user_id}"
                )
                return api_error(
                    "Unauthorized to stop live updates for this event",
                    HTTPStatus.FORBIDDEN
                )

            # Get live query ID from Redis
            live_id = await self._get_live_query(event_id)
            if live_id:
                await self.conn.kill_live_query(live_id)
                await self._remove_live_query(event_id)
                app.logger.info(
                    f"Successfully stopped live updates for event {event_id}"
                )
                return api_response(
                    "Live updates stopped successfully.",
                    HTTPStatus.OK
                )

            app.logger.info(f"No live updates running for event {event_id}")
            return api_response(
                "No live updates running for this event.",
                HTTPStatus.OK
            )

        except Exception as e:
            app.logger.error(
                f"Failed to stop live query for event {event_id}: {str(e)}",
                exc_info=True,
            )
            return api_error(
                f"Failed to stop live updates: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/<event_id>/guestlist", methods=["GET"])
    @jwt_required
    async def get_event_guestlist(self, event_id: str):
        """
        Get the guestlist for an event.
        Returns list of invited users with their invitation details.
        """
        try:
            user_id = get_jwt_identity()
            
            # Check if user has permission to view guestlist
            event = await self.conn.fetch(event_id)
            if not event:
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            # Only allow event host to view guestlist (you can modify this logic)
            if event.get("host", {}).get("id") != user_id:
                return api_error("Only event hosts can view guestlist", HTTPStatus.FORBIDDEN)

            guestlist = await self.conn.fetch_event_guestlist(event_id)
            
            return api_response(
                "Guestlist retrieved successfully",
                HTTPStatus.OK,
                data=guestlist,
            )

        except Exception as e:
            app.logger.error(
                f"Error retrieving guestlist for event {event_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to retrieve guestlist: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/<event_id>/guestlist", methods=["POST"])
    @jwt_required
    async def add_to_guestlist(self, event_id: str):
        """
        Add a user to the event guestlist.
        Body: {"user_id": "user123", "status": "invited"}
        """
        try:
            current_user_id = get_jwt_identity()
            data = await request.get_json()
            
            if not data or not data.get("user_id"):
                return api_error("user_id is required", HTTPStatus.BAD_REQUEST)

            # Check if user has permission to manage guestlist
            event = await self.conn.fetch(event_id)
            if not event:
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            # Only allow event host to manage guestlist (you can modify this logic)
            if event.get("host", {}).get("id") != current_user_id:
                return api_error("Only event hosts can manage guestlist", HTTPStatus.FORBIDDEN)

            target_user_id = data["user_id"]
            invitation_status = data.get("status", "invited")
            
            result = await self.conn.add_to_guestlist(
                event_id=event_id,
                user_id=target_user_id,
                invited_by=current_user_id,
                status=invitation_status
            )
            
            return api_response(
                "User added to guestlist successfully",
                HTTPStatus.CREATED,
                data=result,
            )

        except Exception as e:
            app.logger.error(
                f"Error adding user to guestlist for event {event_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to add user to guestlist: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/<event_id>/guestlist/<user_id>", methods=["DELETE"])
    @jwt_required
    async def remove_from_guestlist(self, event_id: str, user_id: str):
        """
        Remove a user from the event guestlist.
        """
        try:
            current_user_id = get_jwt_identity()
            
            # Check if user has permission to manage guestlist
            event = await self.conn.fetch(event_id)
            if not event:
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            # Only allow event host to manage guestlist (you can modify this logic)
            if event.get("host", {}).get("id") != current_user_id:
                return api_error("Only event hosts can manage guestlist", HTTPStatus.FORBIDDEN)

            success = await self.conn.remove_from_guestlist(event_id, user_id)
            
            if success:
                return api_response("User removed from guestlist successfully", HTTPStatus.OK)
            else:
                return api_error("User not found in guestlist", HTTPStatus.NOT_FOUND)

        except Exception as e:
            app.logger.error(
                f"Error removing user from guestlist for event {event_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to remove user from guestlist: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/<event_id>/guestlist/<user_id>/status", methods=["PATCH"])
    @jwt_required
    async def update_guestlist_status(self, event_id: str, user_id: str):
        """
        Update guestlist invitation status.
        Body: {"status": "accepted|declined|invited"}
        """
        try:
            current_user_id = get_jwt_identity()
            data = await request.get_json()
            
            if not data or not data.get("status"):
                return api_error("status is required", HTTPStatus.BAD_REQUEST)

            # Allow both event host and invited user to update status
            event = await self.conn.fetch(event_id)
            if not event:
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            # Check permission: either event host or the invited user themselves
            is_host = event.get("host", {}).get("id") == current_user_id
            is_invited_user = user_id == current_user_id
            
            if not (is_host or is_invited_user):
                return api_error("Permission denied", HTTPStatus.FORBIDDEN)

            new_status = data["status"]
            result = await self.conn.update_guestlist_status(event_id, user_id, new_status)

            event_name = event.get("title") or event.get("name") or "your event"
            if new_status in ("accepted", "declined"):
                if is_host:
                    asyncio.ensure_future(
                        self._notify_guestlist_decision(
                            guest_id=user_id,
                            event_name=event_name,
                            event_id=event_id,
                            status=new_status,
                        )
                    )
                elif is_invited_user:
                    host_id = str(event.get("host", {}).get("id", "")).split(":")[-1]
                    if host_id:
                        asyncio.ensure_future(
                            self._notify_guestlist_rsvp(
                                host_id=host_id,
                                guest_id=user_id,
                                event_name=event_name,
                                event_id=event_id,
                                status=new_status,
                            )
                        )

            return api_response(
                "Guestlist status updated successfully",
                HTTPStatus.OK,
                data=result,
            )

        except Exception as e:
            app.logger.error(
                f"Error updating guestlist status for event {event_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to update guestlist status: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/<event_id>/media", methods=["PUT"])
    @ValidationMiddleware.validate_file_upload(
        max_size=50 * 1024 * 1024,
        required=True
    )
    @jwt_required
    async def update_event_media(self, event_id: str):
        """
        Update event images/media by replacing all existing media with new uploads.
        Requires multipart/form-data with file uploads.
        """
        try:
            user_id = get_jwt_identity()
            
            # Verify event exists and user has permission
            event = await self.conn.fetch(event_id)
            if not event:
                return api_error("Event not found", HTTPStatus.NOT_FOUND)
            
            if event.get("creator") != user_id:
                return api_error("Unauthorized to update this event", HTTPStatus.FORBIDDEN)
            
            files = await request.files
            if not files:
                return api_error("At least one image file is required", HTTPStatus.BAD_REQUEST)
            
            # Prepare media data
            media_data = []
            filenames = [
                f"events/{user_id}/{event_id}/{str(ruuid.uuid4()).split('-')[-1]}{os.path.splitext(file.filename)[-1]}"
                for file in files.values()
            ]
            
            # Upload files to GCP
            for i, file in enumerate(files.values()):
                file_upload_data = {
                    "filename": filenames[i],
                    "type": file.content_type,
                    "host": user_id,
                    "event_id": RecordID("events", event_id),
                    "creator": user_id,
                }
                app.logger.info(f"Uploading updated event media to GCP: {file_upload_data['filename']}")
                await app.RMQ._publish_media(file_upload_data, file)
                
                media_data.append({
                    "filename": filenames[i],
                    "type": file.content_type,
                    "creator": RecordID("users", user_id),
                })
            
            # Update media in database
            result = await self.conn.update_event_media(event_id, media_data)

            # Invalidate all similar_events cache keys for this event.
            # The recommendations are based on embeddings from the old media
            # which no longer apply once media is replaced.
            try:
                keys = await self.redis.keys(f"similar_events:{event_id}:*")
                if keys:
                    await self.redis.delete(*keys)
                    app.logger.info(f"Invalidated {len(keys)} similar_events cache key(s) for {event_id}")
            except Exception as cache_err:
                app.logger.warning(f"Cache invalidation failed for {event_id}: {cache_err}")

            return api_response(
                "Event media updated successfully",
                HTTPStatus.OK,
                data=result,
            )
            
        except Exception as e:
            app.logger.error(
                f"Error updating media for event {event_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to update event media: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/<event_id>/tickets/verify", methods=["POST"])
    @jwt_required
    async def verify_ticket(self, event_id: str):
        """
        Verify a ticket by scanning its QR code.
        Body: {"ticket_number": "TKT-XXXX-YYYY"}
        
        Response scenarios:
        - Valid ticket, first scan: Returns ticket details with checked_in_at timestamp
        - Valid ticket, already scanned: Returns ticket details with original checked_in_at
        - Invalid ticket: Returns error message
        """
        try:
            user_id = get_jwt_identity()
            data = await request.get_json()
            
            if not data or "ticket_number" not in data:
                return api_error(
                    "ticket_number is required in request body",
                    HTTPStatus.BAD_REQUEST
                )

            # Verify user has permission (event host or authorized staff)
            event = await self.conn.fetch(event_id)
            if not event:
                return api_error("Event not found", HTTPStatus.NOT_FOUND)
            
            # Allow both event host and staff with access to verify tickets
            # You can extend this logic to check for specific roles or permissions
            
            if not self.check_ticket_verify_authorization(event_id, user_id):
                return api_error(
                    "Only event hosts and collectors can verify tickets",
                    HTTPStatus.FORBIDDEN
                )
            
            ticket_number = data["ticket_number"]
            result = await self.conn.verify_ticket(event_id, ticket_number)
            
            if not result.get("valid"):
                return api_error(
                    result.get("message", "Invalid ticket"),
                    HTTPStatus.NOT_FOUND
                )

            # Handle already checked-in tickets differently
            if result.get("already_checked_in"):
                return api_response(
                    "Ticket already checked in",
                    HTTPStatus.OK,
                    data=result,
                )
            else:
                # Fresh check-in — grant the attendee streaming role on the Stream call.
                # This gives the user permission to go live during the event.
                # Role is geofenced: POST /scenes/<event_id>/attendee-location revokes it
                # if the user leaves the party radius.
                # Non-fatal: a Stream error must never block a successful ticket scan.
                try:
                    checked_in_user_id = (result.get("ticket") or {}).get("user", {}).get("id")
                    if checked_in_user_id:
                        call_id = f"partyscene-{event_id}"
                        call    = _stream_video.video.call("livestream", call_id)
                        await asyncio.to_thread(
                            call.update_call_members,
                            update_members=[_MemberRequest(user_id=checked_in_user_id, role="attendee")],
                        )
                        app.logger.info(f"✅ Granted attendee streaming role: user={checked_in_user_id} call={call_id}")
                except Exception as stream_err:
                    app.logger.warning(f"⚠️ Failed to grant attendee role for {event_id}: {stream_err}")

                BusinessMetrics.TICKET_CHECKINS.inc()

                host_id = str(event.get("host", {}).get("id", "")).split(":")[-1]
                if host_id:
                    ticket_obj = result.get("ticket") or {}
                    attendee_name = (
                        ticket_obj.get("guest_name")
                        or ticket_obj.get("user", {}).get("username")
                        or "Attendee"
                    )
                    asyncio.ensure_future(
                        self._notify_ticket_checkin(
                            host_id=host_id,
                            event_name=event.get("title", "your event"),
                            event_id=event_id,
                            attendee_name=attendee_name,
                            ticket_number=ticket_number,
                        )
                    )

                return api_response(
                    "Ticket verified and checked in successfully",
                    HTTPStatus.OK,
                    data=result,
                )
        
        except Exception as e:
            app.logger.error(
                f"Error verifying ticket for event {event_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to verify ticket: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/<event_id>/tiers", methods=["GET"])
    async def get_tiers(self, event_id: str):
        """Fetch all ticket tiers for an event"""
        try:
            event = await self.conn.fetch(event_id)
            if not event:
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            tiers = await self.conn.fetch_event_tiers(event_id)
            return api_response(
                "Event tiers fetched successfully",
                HTTPStatus.OK,
                data=tiers,
            )
        except Exception as e:
            app.logger.error(
                f"Error fetching tiers for event {event_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to fetch tiers: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/<event_id>/tiers", methods=["POST"])
    @jwt_required
    async def create_tier(self, event_id: str):
        """Create a ticket tier for an event (host only, max 3)"""
        try:
            user_id = get_jwt_identity()

            event = await self.conn.fetch(event_id)
            if not event:
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            if event.get("host", {}).get("id") != user_id:
                return api_error(
                    "Only event hosts can manage tiers",
                    HTTPStatus.FORBIDDEN
                )

            data = await request.get_json()
            if not data or not data.get("name") or data.get("price") is None:
                return api_error(
                    "name and price are required",
                    HTTPStatus.BAD_REQUEST
                )

            tier_data = {
                "name": data["name"],
                "price": float(data["price"]),
            }
            if "capacity" in data and data["capacity"] is not None:
                tier_data["capacity"] = int(data["capacity"])
            if "description" in data:
                tier_data["description"] = str(data["description"])

            result = await self.conn.create_ticket_tier(event_id, tier_data)
            return api_response(
                "Tier created successfully",
                HTTPStatus.CREATED,
                data=result,
            )
        except ValueError as e:
            return api_error(str(e), HTTPStatus.BAD_REQUEST)
        except Exception as e:
            app.logger.error(
                f"Error creating tier for event {event_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to create tier: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/<event_id>/tiers/<tier_id>", methods=["PATCH"])
    @jwt_required
    async def update_tier(self, event_id: str, tier_id: str):
        """Update a ticket tier (host only)"""
        try:
            user_id = get_jwt_identity()

            event = await self.conn.fetch(event_id)
            if not event:
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            if event.get("host", {}).get("id") != user_id:
                return api_error(
                    "Only event hosts can manage tiers",
                    HTTPStatus.FORBIDDEN
                )

            data = await request.get_json()
            if not data:
                return api_error(
                    "Request body is required",
                    HTTPStatus.BAD_REQUEST
                )

            result = await self.conn.update_ticket_tier(tier_id, data)
            return api_response(
                "Tier updated successfully",
                HTTPStatus.OK,
                data=result,
            )
        except Exception as e:
            app.logger.error(
                f"Error updating tier {tier_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to update tier: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/events/<event_id>/tiers/<tier_id>", methods=["DELETE"])
    @jwt_required
    async def delete_tier(self, event_id: str, tier_id: str):
        """Delete a ticket tier (host only, no sold tickets)"""
        try:
            user_id = get_jwt_identity()

            event = await self.conn.fetch(event_id)
            if not event:
                return api_error("Event not found", HTTPStatus.NOT_FOUND)

            if event.get("host", {}).get("id") != user_id:
                return api_error(
                    "Only event hosts can manage tiers",
                    HTTPStatus.FORBIDDEN
                )

            await self.conn.delete_ticket_tier(tier_id)
            return api_response(
                "Tier deleted successfully",
                HTTPStatus.OK,
            )
        except ValueError as e:
            return api_error(str(e), HTTPStatus.BAD_REQUEST)
        except Exception as e:
            app.logger.error(
                f"Error deleting tier {tier_id}: {str(e)}", exc_info=True
            )
            return api_error(
                f"Failed to delete tier: {str(e)}",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )