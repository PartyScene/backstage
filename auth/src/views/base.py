import datetime
import random

from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify

from ..classful import route, QuartClassful


class BaseView(QuartClassful):
    app = app
    route_base = "auth/"

    @route("/register", methods=["POST"])
    async def register(self):
        """Register a user account into the SurrealDB.

        Args:
            id (str): _description_
        """
        ...
        # if request.method == "POST":
        #     form = await request.form()
        #     await app.db._create(form)
