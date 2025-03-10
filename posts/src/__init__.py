import asyncio
import json
from pprint import pprint
import os
import logging
from logging.config import dictConfig

from quart_schema import QuartSchema
from quart import Quart, request, websocket
from quart_jwt_extended import JWTManager, jwt_required, get_jwt_identity

from redis.asyncio import Redis

from .connectors import PostsDB, init_db
from .views.base import BaseView

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


class PostsMicroService(Quart):
    def __init__(self, *args):
        super(PostsMicroService, self).__init__(*args)
        QuartSchema(self)

        self.conn: PostsDB = None
        self.redis: Redis = None

        # Set dev environment settings
        if os.getenv("ENVIRONMENT") == "dev":
            self.config["DEBUG"] = True
            self.config["TESTING"] = True
            self.DEBUG = True

        logger.info(self.config)

        # Initialize Redis with decode_responses=True
        # self.config["REDIS_URL"] = self.config.get("REDIS_URI", "redis://redis")
        self.config["REDIS_DECODE_RESPONSES"] = True

        @self.before_request
        async def log_request():
            logger.info(f"Request received: {request.method} {request.path}")
            logger.debug(f"Request headers: {request.headers}")
            logger.debug(f"Request body: {await request.get_json()}")

        @self.after_request
        async def log_response(response):
            logger.info(f"Response sent: {response.status_code}")
            return response

        @self.before_serving
        async def services():
            """Initialize services before app is being served."""
            logger.info("Initializing services...")
            await self.init_services()
            self.register_routes()

        @self.after_serving
        async def cleanup():
            """Cleanup resources after app is being stopped."""
            logger.info("Cleaning up resources...")
            await self.clean_up()

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
            # Initialize DB
            await self.init_redis()
            self.conn = await init_db(self)

            # Get JWT secret
            logger.info("Retrieving JWT secret...")
            await self.get_shared_secret()

            logger.info("All services initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize services: {str(e)}", exc_info=True)
            raise

    def register_routes(self):
        # Register routes
        logger.info("Registering application routes...")
        BaseView.register(self)

        # Register WebSocket routes

        logger.info("Printing Application Routes...")
        logger.info(self.url_map)

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

    async def clean_up(self):
        """
        Gracefully shutdown SurrealDB and Redis connections.

        This method ensures that database connections are closed properly,
        with detailed logging and error handling to prevent resource leaks.
        """
        try:
            logger.info("Starting service cleanup process...")

            # Close SurrealDB connection
            if hasattr(self, "conn") and self.conn is not None:
                try:
                    logger.info("Closing SurrealDB connection...")
                    await self.conn.db.close()
                    logger.info("SurrealDB connection closed successfully")
                except Exception as db_close_error:
                    logger.error(
                        f"Error closing SurrealDB connection: {str(db_close_error)}",
                        exc_info=True,
                    )

            # Close Redis connection
            if hasattr(self, "redis") and self.redis is not None:
                try:
                    logger.info("Closing Redis connection...")
                    await self.redis.close()
                    logger.info("Redis connection closed successfully")
                except Exception as redis_close_error:
                    logger.error(
                        f"Error closing Redis connection: {str(redis_close_error)}",
                        exc_info=True,
                    )

            logger.info("Service cleanup completed successfully")
        except Exception as general_error:
            logger.error(
                f"Unexpected error during service cleanup: {str(general_error)}",
                exc_info=True,
            )
            raise
