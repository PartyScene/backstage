from pprint import pprint
import secrets

from quart_schema import QuartSchema
import uvloop
import logging

from quart import Quart
from .connectors import init_db
from .views.base import BaseView

from quart_redis import RedisHandler
from quart_jwt_extended import (
    JWTManager
)


class AuthMicroService(Quart):

    def __init__(self, *args):
        super(AuthMicroService, self).__init__(*args)
        QuartSchema(self)

        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
        )

        self.db = None  # Asyncpg pool
        self.logging = logging
        self.config.from_pyfile("src/settings.py")
        self.redis_handler = RedisHandler(self)
        self.jwt = JWTManager(self)

        self.before_serving(self.services)

    async def services(self):
        """Initialize db before app is being served."""
        logging.info("Initializing SurrealDB Database Connection...")
        self.db = await init_db(self)

        logging.info("Registering Application Routes.")
        BaseView.register(self)
        
        logging.info("Printing Application Routes...")
        logging.info(self.url_map)
        
        logging.info("Pushing Secret...")
        await self.set_shared_secret()
        
    
    async def set_shared_secret(self):
        """"""
        conn = self.redis_handler.get_connection()
        self.config['SECRET_KEY'] = secrets.token_hex(32)
        await conn.set("SECRET_KEY", self.config['SECRET_KEY'])

    def run(self):
        """Custom Run Method."""
        super(AuthMicroService, self).run(
            host="0.0.0.0", port=5510, loop=uvloop.new_event_loop()
        )
