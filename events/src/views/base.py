import datetime
import random

from dataclasses import dataclass
from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify
from quart_schema import  document_querystring, DataSource

from ..connectors import EventsDB
from ..schema import Events
from ..classful import route, QuartClassful

from quart_jwt_extended import (
    get_jwt_identity, jwt_required
)


class BaseView(QuartClassful):
    app = app
    
    def __init__(self):
        self.db : EventsDB = app.db
        
    route_base = "/events/"

    @route("/all", methods=["GET"])
    @jwt_required
    @document_querystring(Events)
    async def fetch_all(self):
        """This endpoints returns all the events"""
        result = await self.db.events.fetch_all()
        return result, 200
