import uvloop
import logging

from quart import Quart
# from .connectors import init_db
from .views.base import BaseView


class UsersMicroService(Quart):
    
    def __init__(self, *args):
        super(UsersMicroService, self).__init__(*args)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        
        self.pool = None # Asyncpg pool
        self.config.from_pyfile("src/settings.py")
        
        self.before_serving(self.services)
        
    async def services(self):
        """Initialize db before app is being served.
        """
        logging.info("Intitializing Database Connection.")
        # self.pool = await init_db(self)

        logging.info("Registering Application Routes.")
        BaseView.register(self)
        
    def run(self):
        """Custom Run Method.
        """
        super(UsersMicroService, self).run(host="0.0.0.0", port=5510, loop=uvloop.new_event_loop())