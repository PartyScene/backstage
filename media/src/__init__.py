from pprint import pprint
import secrets
import os

from quart_schema import QuartSchema
import uvloop
import logging
from logging.config import dictConfig

from quart import Quart, app, request
from .connectors import init_db
from .views.base import BaseView

from quart_jwt_extended import JWTManager
from redis.asyncio import Redis

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


class MediaMicroService(Quart):

    def __init__(self, *args):
        super(MediaMicroService, self).__init__(*args)
        QuartSchema(self)
        self.db = None  # Asyncpg pool
        self.redis = None

        # Set dev environment settings
        if os.getenv("ENVIRONMENT") == "dev":
            self.config["DEBUG"] = True
            self.config["TESTING"] = True
            self.DEBUG = True

        # Initialize Redis with decode_responses=True
        self.config["REDIS_DECODE_RESPONSES"] = True

        # These functions are preprocessing methods

        @self.before_request
        async def log_request():
            logger.info("Retrieving Secret...")
            await self.get_shared_secret()
            logger.info(f"Request received: {request.method} {request.path}")
            logger.debug(f"Request headers: {request.headers}")
            logger.debug(f"Request body: {await request.get_json()}")
            logger.debug(f"Request files: {await request.files}")
            logger.debug(f"KEYS: {self.config['SECRET_KEY']}")

        @self.after_request
        async def log_response(response):
            logger.info(f"Response sent: {response.status_code}")
            return response

        @self.before_serving
        async def services():
            """Initialize services before app is being served."""
            logger.info("Initializing services...")
            await self.init_services()

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

    async def init_services(self):
        """Initialize all required services"""
        try:
            await self.init_redis()
            # Initialize DB
            if not self.DEBUG:
                logger.info("Initializing SurrealDB connection...")
                self.db = await init_db(self)

            # Get JWT secret
            logger.info("Retrieving JWT secret...")
            await self.get_shared_secret()

            logger.info("All services initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize services: {str(e)}", exc_info=True)
            raise

    async def get_shared_secret(self):
        """Get JWT secret from Redis"""
        try:
            secret = await self.redis.get("SECRET_KEY")
            if not secret:
                raise ValueError("JWT secret not found in Redis")

            self.config["SECRET_KEY"] = secret
            self.config["JWT_SECRET_KEY"] = self.config["SECRET_KEY"]
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
