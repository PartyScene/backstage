import datetime
import random

from dataclasses import dataclass
from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify
from quart_schema import validate_request, validate_response, document_querystring

from src.connectors import AuthDB
from src.schema import FormIn, LoginForm
from ..classful import route, QuartClassful

from quart_jwt_extended import create_access_token


class BaseView(QuartClassful):

    def __init__(self):
        self.db: AuthDB = app.db
        
    @route("/register", methods=["POST"])
    @validate_request(FormIn)
    async def _register(self, data: FormIn):
        """
        Register a user account into the SurrealDB.
        """
        ...
        await self.db._create(data)
        return "", 200

    @route("/login", methods=["POST"])
    @validate_request(LoginForm)
    async def login_user(self, data: LoginForm):
        """
        Verify user credentials
        """
        ...
        if await self.db._login(data):
            access_token = create_access_token(identity=data.email)
            return dict(access_token=access_token), 200
