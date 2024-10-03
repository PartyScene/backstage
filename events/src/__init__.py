from pprint import pprint

from quart_schema import QuartSchema
import uvloop
import logging

from quart import Quart
from .connectors import EventsDB, init_db
from .views.base import BaseView


class EventsMicroService(Quart):

    def __init__(self, *args):
        super(EventsMicroService, self).__init__(*args)
        QuartSchema(self)

        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
        )

        self.db : EventsDB = None  # Asyncpg pool
        self.logging = logging
        self.config.from_pyfile("src/settings.py")

        self.before_serving(self.services)

    async def services(self):
        """Initialize db before app is being served."""
        logging.info("Initializing SurrealDB Database Connection...")
        self.db = await init_db(self)

        logging.info("Registering Application Routes.")
        BaseView.register(self)
        logging.info("Printing Application Routes...")
        logging.info(self.url_map)

    def run(self):
        """Custom Run Method."""
        super(EventsMicroService, self).run(
            host="0.0.0.0", port=5510, loop=uvloop.new_event_loop()
        )
