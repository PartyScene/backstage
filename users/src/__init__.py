from pprint import pprint
import secrets

from quart_schema import QuartSchema
import logging
import os
from logging.config import dictConfig

from quart import Quart, request
from .connectors import init_db
from .views.base import BaseView

from redis.asyncio import Redis
from quart_jwt_extended import JWTManager

# Configure logging
dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": "INFO",
            }
        },
        "root": {
            "handlers": ["console"],
            "level": "INFO",
        },
    }
)

logger = logging.getLogger(__name__)


class UsersMicroService(Quart):

    def __init__(self, *args):
        super(UsersMicroService, self).__init__(*args)

        self.db = None  # SurrealDB
        self.redis = None

        # Set dev environment settings
        if os.getenv("ENVIRONMENT") == "dev":
            self.config["DEBUG"] = True
            self.config["TESTING"] = True
            self.DEBUG = True

        self.config["REDIS_DECODE_RESPONSES"] = True

        @self.before_request
        async def log_request():
            logger.info(f"Request received: {request.method} {request.path}")
            logger.debug(f"Request headers: {request.headers}")
            logger.debug(f"Request body as Raw: {await request.get_data()}")
            logger.debug(
                f"Request body as Form: {await request.get_data(parse_form_data=True)}"
            )
            logger.debug(f"Request files: {await request.files}")
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
        logger.info("Initializing Redis Connection...")
        await self.init_redis()

        if not self.DEBUG:
            logger.info("Initializing SurrealDB connection...")
            self.db = await init_db(self)

        logger.info("Retrieving Secret...")
        await self.get_shared_secret()

    async def init_redis(self):
        """Initialize Redis connection"""
        try:
            logger.info("Initializing Redis connection...")
            self.redis = Redis.from_url(
                os.environ["REDIS_URI"], decode_responses=True, encoding="utf-8"
            )
            # Test connection
            await self.redis.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.error(f"Failed to initialize Redis: {str(e)}")
            raise

    async def get_shared_secret(self):
        """Get JWT secret from Redis"""
        try:
            secret = await self.redis.get("SECRET_KEY")
            if not secret:
                raise ValueError("JWT secret not found in Redis")

            self.config["SECRET_KEY"] = secret
            self.jwt = JWTManager(self)
            logger.info("JWT secret retrieved and manager initialized")

        except Exception as e:
            logger.error(f"Failed to get JWT secret: {str(e)}", exc_info=True)
            raise

    def register_routes(self):
        # Register routes
        logger.info("Registering application routes...")
        BaseView.register(self)

        logger.info("Printing Application Routes...")
        logger.info(self.url_map)
