from pprint import pprint

from quart_redis import RedisHandler
from quart_schema import QuartSchema
import uvloop
import logging

from quart import Quart, request
from quart_jwt_extended import JWTManager

from .connectors import EventsDB, init_db
from .views.base import BaseView


class EventsMicroService(Quart):

    def __init__(self, *args):
        super(EventsMicroService, self).__init__(*args)
        QuartSchema(self)

        logging.basicConfig(
            level=logging.INFO , format="%(asctime)s %(levelname)s %(message)s"
        )

        self.db: EventsDB = None  # Asyncpg pool
        self.logging = logging
        self.config.from_pyfile("/app/shared/settings.py")

        self.redis_handler = RedisHandler(self)

        self.before_serving(self.services)
        
    
        @self.before_request
        async def log_request():
            logging.info("Retrieving Secret...")
            await self.get_shared_secret()
            self.logging.info(f"Request received: {request.method} {request.path}")
            self.logging.debug(f"Request body: {await request.get_json()}")
            self.logging.debug(f"KEYS: {self.config['SECRET_KEY']}")

            
    async def services(self):
        """Initialize db before app is being served."""
        logging.info("Initializing SurrealDB Database Connection...")
        self.db = await init_db(self)

        logging.info("Registering Application Routes.")
        BaseView.register(self)

        logging.info("Printing Application Routes...")
        logging.info(self.url_map)

    async def get_shared_secret(self):
        """"""
        conn = self.redis_handler.get_connection()
        self.config["SECRET_KEY"] = await conn.get("SECRET_KEY")

        # Then Initialize JWT
        self.jwt = JWTManager(self)

    def run(self):
        """Custom Run Method."""
        super(EventsMicroService, self).run(
            host="0.0.0.0", port=5510, loop=uvloop.new_event_loop()
        )




