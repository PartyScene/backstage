from pprint import pprint
import secrets

import logging
from logging.config import dictConfig

from quart import Quart, app, request
from .connectors import init_db
from .views.base import BaseView

from quart_redis import RedisHandler, get_redis
from quart_jwt_extended import JWTManager
# Configure logging
dictConfig({
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'level': 'INFO',
        }
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    }
})

logger = logging.getLogger(__name__)

class PostsMicroservice(Quart):

    def __init__(self, *args):
        super(PostsMicroservice, self).__init__(*args)
        self.db = None
        self.config.from_pyfile("/app/shared/settings.py")
        self.redis_handler = RedisHandler(self)
        
        # These functions are preprocessing methods.
    
        @self.before_request
        async def log_request():
            logger.info(f"Request received: {request.method} {request.path}")
            logger.debug(f"Request headers: {request.headers}")
            # logger.debug(f"Request body: {await request.get_json()}")
            # logger.debug(f"Request files: {await request.files}")
            logger.debug(f"KEYS: {self.config['SECRET_KEY']}")

        @self.before_serving
        async def before_serv():
            await self.services()

        @self.after_request
        async def log_response(response):
            logger.info(f"Response sent: {response.status_code}")
            return response

    async def services(self):
        """Initialize db before app is being served."""
        logging.info("Initializing SurrealDB Database Connection...")
        self.db = await init_db(self)

        logging.info("Registering Application Routes.")
        BaseView.register(self)

        logging.info("Printing Application Routes...")
        logging.info(self.url_map)

        logging.info("Retrieving Secret...")
        await self.get_shared_secret()

    
    async def get_shared_secret(self):
        """Get JWT secret from Redis"""
        try:
            redis = await get_redis()
            secret = await redis.get("SECRET_KEY")
            if not secret:
                raise ValueError("JWT secret not found in Redis")
                
            self.config["SECRET_KEY"] = secret
            self.jwt = JWTManager(self)
            logger.info("JWT secret retrieved and manager initialized")
            
        except Exception as e:
            logger.error(f"Failed to get JWT secret: {str(e)}", exc_info=True)
            raise