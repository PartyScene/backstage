from quart import current_app as app, request, jsonify
from quart.datastructures import FileStorage
from quart_jwt_extended import get_jwt_identity, jwt_required

from ..connectors import UsersDB

from ..classful import route, QuartClassful


class BaseView(QuartClassful):
    
    def __init__(self):
        self.db : UsersDB = app.db

    @route("/users/", methods=["GET", "POST"])
    @jwt_required
    async def index(self):
        """Fetch a USER profile"""
        ...
        data = await request.get_json()
        response = await self.db.users.fetch(data['email'])
        return response, 200
        
    @route("/me", methods=["GET", "POST", "PUT", "PATCH"])
    @jwt_required
    async def me(self):
        """Fetch the current authenticated user"""
        response = await self.db.users.fetch(get_jwt_identity())
        return response, 200