from dataclasses import dataclass
from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify
from quart_schema import validate_request, validate_response, document_querystring

from src.connectors import AuthDB

import sys
sys.path.append('/app/shared')

from classful import route, QuartClassful

from quart_jwt_extended import create_access_token


class BaseView(QuartClassful):

    def __init__(self):
        self.db: AuthDB = app.db
        
    @route("/register", methods=["POST"])
    async def _register(self):
        """
        Register a user account into the SurrealDB.
        """
        data = await request.get_json()
        await self.db._create(data)
        return "", 200

    @route("/login", methods=["POST"])
    async def login_user(self):
        """
        Verify user credentials
        """
        data = request.get_json()
        if await self.db._login(data):
            access_token = create_access_token(identity=data['email'])
            return dict(access_token=access_token), 200
