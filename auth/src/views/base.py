import datetime
import random

from dataclasses import dataclass
from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify
from quart_schema import validate_request, validate_response, document_querystring

from src.schema import FormIn
from ..classful import route, QuartClassful


class BaseView(QuartClassful):
    app = app
    route_base = "/auth/"

    @route("/register", methods=["POST"])
    @validate_request(FormIn)
    @document_querystring(FormIn)
    async def _register(self, data: FormIn):
        """Register a user account into the SurrealDB."""
        ...
        await app.db._create(data)
        return "", 200
