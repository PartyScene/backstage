import logging
from logging.config import dictConfig

from quart_schema import QuartSchema
from quart import Quart, request
from quart_redis import RedisHandler, get_redis
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

class LiveStreamMicroservice(Quart):
    def __init__(self, *args):
        super(LiveStreamMicroservice, self).__init__(*args)
        QuartSchema(self)

        self.db = None
        self.config.from_pyfile("/app/shared/settings.py")
        
        # Initialize Redis with decode_responses=True
        self.config["REDIS_DECODE_RESPONSES"] = True
        self.redis_handler = RedisHandler(self)

        @self.before_request
        async def log_request():
            logger.info(f"Request received: {request.method} {request.path}")
            logger.debug(f"Request headers: {request.headers}")
            try:
                body = await request.get_json()
                logger.debug(f"Request body: {body}")
            except Exception:
                pass

        @self.after_request
        async def log_response(response):
            logger.info(f"Response sent: {response.status_code}")
            return response

        @self.before_serving
        async def services():
            """Initialize services before app is being served."""
            logger.info("Initializing services...")
            await self.init_services()

    async def init_services(self):
        """Initialize all required services"""
        try:
            # Initialize DB
            logger.info("Initializing SurrealDB connection...")
            self.db = await init_db(self)
            
            # Get JWT secret
            logger.info("Retrieving JWT secret...")
            await self.get_shared_secret()
            
            # Register routes
            logger.info("Registering application routes...")
            BaseView.register(self)
            
            logger.info("All services initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize services: {str(e)}", exc_info=True)
            raise

    async def get_shared_secret(self):
        """Get JWT secret from Redis"""
        try:
            redis = await get_redis()
            secret = await redis.get("SECRET_KEY")
            if not secret:
                raise ValueError("JWT secret not found in Redis")
                
            self.config["SECRET_KEY"] = secret
            self.config["JWT_SECRET_KEY"] = self.config["SECRET_KEY"]
            self.jwt = JWTManager(self)
            logger.info("JWT secret retrieved and manager initialized")
            
        except Exception as e:
            logger.error(f"Failed to get JWT secret: {str(e)}", exc_info=True)
            raise