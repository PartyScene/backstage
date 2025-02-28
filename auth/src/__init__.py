import logging
import os
import secrets

from logging.config import dictConfig

from redis.asyncio import Redis
from quart_schema import QuartSchema
from quart import Quart, request
from quart_jwt_extended import JWTManager

from .connectors import init_db
from .views.base import BaseView

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

class AuthMicroService(Quart):
    def __init__(self, *args):
        self.DEBUG = False
        
        super(AuthMicroService, self).__init__(*args)
        QuartSchema(self)

        self.db = None
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

    async def init_redis(self):
        """Initialize Redis connection"""
        try:
            logger.info("Initializing Redis connection...")
            self.redis = Redis.from_url(
                os.environ["REDIS_URI"],
                decode_responses=True,
                encoding="utf-8"
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
            if not self.DEBUG:
                logger.info("Initializing SurrealDB connection...")
                self.db = await init_db(self)
            
            # Set JWT secret
            logger.info("Setting JWT secret...")
            await self.set_shared_secret()
            
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

    async def cleanup(self):
        """Cleanup connections on shutdown"""
        if self.redis:
            await self.redis.close()
            logger.info("Redis connection closed")

    def register_routes(self):
        # Register routes
        logger.info("Registering application routes...")
        BaseView.register(self)