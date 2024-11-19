import datetime
import random

from dataclasses import dataclass
from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify
from quart_schema import document_querystring, DataSource

from ..connectors import EventsDB
from ..schema import Events
from ..classful import route, QuartClassful

from quart_jwt_extended import get_jwt_identity, jwt_required


class BaseView(QuartClassful):
    app = app

    def __init__(self):
        self.db: EventsDB = app.db

    route_base = "/events/"

    @route("/all", methods=["GET"])
    @jwt_required
    @document_querystring(Events)
    async def fetch_all(self):
        """This endpoints returns all the events"""
        result = await self.db.events.fetch_all()
        return result, 200
    
    @route("/events/location", methods=["GET"])
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
        result = await self.db.events.fetch_by_distance(location, distance)
        return result, 200
