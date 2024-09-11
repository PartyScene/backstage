import datetime, aioipfs
import random

from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify
from quart.datastructures import FileStorage

from ..classful import route, QuartClassful


class BaseView(QuartClassful):
    app = app
    route_base = "/users/"

    @route("/<id>", methods=["GET", "POST"])
    async def index(self, id: str):
        """Fetch a USER profile"""
        ...
