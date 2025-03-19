import logging
import os
import secrets

from logging.config import dictConfig

from redis.asyncio import Redis
from quart import Quart, request
from quart_jwt_extended import JWTManager, jwt_required

from .enum import Microservice
from typing import Callable
from shared.classful import QuartClassful

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
            "level": "DEBUG",
        },
    }
)

logger = logging.getLogger(__name__)


class MicroService(Quart):
    def __init__(
        self,
        instance: str,
        initialize_database: Callable,
        views: QuartClassful,
        *args,
        **kw,
    ):
        super(MicroService, self).__init__(__name__, *args, **kw)

        self.conn = None
        self.pool_manager: SurrealDBPoolManager = None
        self.redis = None
        self.views = views
        self.initialize_database = initialize_database
        self.microservice_instance = Microservice(instance)

        # Set dev environment settings
        if os.getenv("ENVIRONMENT") == "dev":
            self.config["DEBUG"] = True
            self.config["TESTING"] = True

        self.config["REDIS_DECODE_RESPONSES"] = True

        @self.before_request
        async def log_request():
            logger.debug(f"Request body: {await request.get_json()}")

        @self.after_request
        async def log_response(response):
            if response.status_code not in [200, 201, 204]:
                logger.info(f"Response sent: {response.status_code}")
            return response

        @self.before_serving
        async def services():
            """Initialize services before app is being served."""
            logger.info("Initializing services...")
            await self.init_services()
            self.register_routes()
            if self.microservice_instance == Microservice.EVENTS:
                self.register_websocket_routes()

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
            # Initialize Redis
            await self.init_redis()

            # Initialize DB
            self.conn, self.pool_manager = await self.initialize_database(self)

            # If this MicroService handles authentication, then Set JWT secret
            if self.microservice_instance == Microservice.AUTH:
                logger.info("Setting JWT secret...")
                await self.set_shared_secret()

            else:
                logger.info("Getting JWT secret...")
                await self.get_shared_secret()

            logger.info("All services initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize services: {str(e)}", exc_info=True)
            raise

    async def set_shared_secret(self):
        """Set JWT secret in Redis if it doesn't exist"""
        try:
            # Check if secret already exists
            existing_secret = await self.redis.get("SECRET_KEY")
            if existing_secret:
                logger.info("Using existing JWT secret from Redis")
                self.config["SECRET_KEY"] = existing_secret
            else:
                # Generate and set new secret
                logger.info("Generating new JWT secret")
                self.config["SECRET_KEY"] = secrets.token_hex(32)
                await self.redis.set("SECRET_KEY", self.config["SECRET_KEY"])
                logger.info("New JWT secret stored in Redis")

            # Set JWT secret key and initialize manager
            self.config["JWT_SECRET_KEY"] = self.config["SECRET_KEY"]
            self.jwt = JWTManager(self)
            logger.info("JWT manager initialized")

        except Exception as e:
            logger.error(f"Failed to handle JWT secret: {str(e)}", exc_info=True)
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
                    # await self.conn._close_pools()
                    await self.pool_manager._close_pools()
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

    def register_routes(self):
        # Register routes
        logger.info("Registering application routes...")
        self.views.register(self)

        logger.info("Printing Application Routes...")
        logger.info(self.url_map)

    def register_websocket_routes(self):
        """Register WebSocket routes"""

        @self.websocket("/events/<event_id>/live/ws")
        @jwt_required
        async def event_live_updates(event_id: str):
            try:
                user_id = await get_jwt_identity()

                # Verify user has access to this event
                event = await self.conn.fetch(event_id)
                if not event or (
                    event["host"]["id"] != user_id
                    and user_id not in [a["id"] for a in event.get("attendees", [])]
                ):
                    logger.warning(
                        f"Unauthorized WebSocket connection attempt for event {event_id}"
                    )
                    return

                # Get live query ID from Redis using get_redis()
                live_id = await self.redis.get(f"live_query:{event_id}")
                if not live_id:
                    logger.warning(f"No live query found for event {event_id}")
                    return

                await websocket.accept()
                logger.info(f"WebSocket connection accepted for event {event_id}")

                try:
                    notifications: asyncio.Queue = (
                        await self.conn.get_live_notifications(live_id)
                    )
                    while True:
                        try:
                            if not websocket.connected:
                                break

                            notification = await notifications.get()
                            if notification:
                                await websocket.send(json.dumps(notification))

                        except asyncio.QueueEmpty:
                            break

                except Exception as e:
                    logger.error(f"WebSocket error: {str(e)}", exc_info=True)
                finally:
                    try:
                        await self.conn.kill_live_query(live_id)
                        await self.redis.delete(f"live_query:{event_id}")
                        logger.info(f"Cleaned up resources for event {event_id}")
                    except Exception as e:
                        logger.error(f"Cleanup error: {str(e)}", exc_info=True)

            except Exception as e:
                logger.error(f"Live updates error: {str(e)}", exc_info=True)
