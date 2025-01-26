from pprint import pprint
import secrets

from quart_schema import QuartSchema
import logging
from logging.config import dictConfig

from quart import Quart, request
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

class UsersMicroService(Quart):

    def __init__(self, *args):
        super(UsersMicroService, self).__init__(*args)

        self.db = None  # SurrealDB
        self.config.from_pyfile("/app/shared/settings.py")
        self.redis_handler = RedisHandler(self)

        @self.before_request
        async def log_request():
            logger.info(f"Request received: {request.method} {request.path}")
            logger.debug(f"Request headers: {request.headers}")
            logger.debug(f"KEYS: {self.config['SECRET_KEY']}")

        @self.after_request
        async def log_response(response):
            logger.info(f"Response sent: {response.status_code}")
            return response
    
        @self.before_serving
        async def before_serv():
            await self.services()

    async def services(self):
        """Initialize db before app is being served."""
        logger.info("Initializing SurrealDB Database Connection...")
        self.db = await init_db(self)

        logger.info("Registering Application Routes.")
        BaseView.register(self)

        logger.info("Printing Application Routes...")
        logger.info(self.url_map)

        logger.info("Retrieving Secret...")
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