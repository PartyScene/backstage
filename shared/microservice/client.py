import logging
import os
import asyncio
import orjson as json
import secrets

from logging.config import dictConfig
from shared.workers import rmq

from redis.asyncio import Redis
from quart import Quart, request, websocket
from quart_jwt_extended import JWTManager, jwt_required, get_jwt_identity

from .enum import Microservice
from typing import Callable
from shared.classful import QuartClassful
from purreal import SurrealDBPoolManager, SurrealDBConnectionPool

# Import middleware components
from shared.middleware import (
    RateLimitMiddleware, 
    ValidationMiddleware, 
    SecurityMiddleware, 
    ErrorHandlerMiddleware
)
from shared.middleware.security import SecurityConfig

# Configure logging
dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
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


######## METRICS

import time
from functools import wraps
from quart import request, current_app
from prometheus_client import Counter, Histogram, Gauge, Summary

# Define metrics
REQUEST_COUNT = Counter(
    "request_count", "App Request Count", ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "request_latency_seconds", "Request latency", ["method", "endpoint"]
)
REQUESTS_IN_PROGRESS = Gauge(
    "requests_in_progress", "Requests in progress", ["method", "endpoint"]
)
DB_QUERY_LATENCY = Histogram("db_query_latency_seconds", "Database query latency")
REDIS_OPERATION_LATENCY = Histogram(
    "redis_operation_latency_seconds", "Redis operation latency"
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
        super().__init__(__name__, *args, **kw)

        self.conn = None
        self.pool_manager: SurrealDBPoolManager = None
        self.redis = None
        self.RMQ: rmq.RMQBroker
        self.views = views
        self.initialize_database = initialize_database
        self.microservice_instance = Microservice(instance)

        # Initialize middleware components
        self.security = SecurityMiddleware(self)
        self.validation = ValidationMiddleware()
        self.error_handler = ErrorHandlerMiddleware(self)
        self.rate_limiter = RateLimitMiddleware(self)
        
        # Configure content length limit before middleware (Quart processes this early)
        self.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
        
        # Configure security settings based on environment
        if os.getenv("ENVIRONMENT") == "dev":
            self.config["DEBUG"] = True
            self.config["TESTING"] = True
            self.config["CORS_ORIGINS"] = SecurityConfig.DEV_CORS_ORIGINS
        else:
            self.config["CORS_ORIGINS"] = SecurityConfig.PROD_CORS_ORIGINS
            # Force HTTPS URLs in production for Stripe compatibility
            self.config["PREFERRED_URL_SCHEME"] = "https"

        @self.before_request
        async def log_request():
            request._log_start = time.time()

        @self.after_request
        async def log_response(response):
            path = request.path
            if path == "/" or path.startswith("/health"):
                return response

            elapsed = time.time() - getattr(
                request, "_log_start", time.time()
            )
            method = request.method
            status = response.status_code
            args = dict(request.args) or None
            user = request.headers.get("X-User-Id", "-")

            # Parse request body (skip binary/multipart)
            req_body = None
            ct = request.content_type or ""
            if "json" in ct or "form" in ct:
                raw = await request.data
                if raw:
                    try:
                        req_body = json.loads(raw)
                    except Exception:
                        req_body = raw.decode(
                            "utf-8", errors="replace"
                        )[:500]

            # Parse response body
            res_body = None
            rct = response.content_type or ""
            if "json" in rct:
                raw = await response.data
                if raw:
                    try:
                        res_body = json.loads(raw)
                    except Exception:
                        res_body = raw.decode(
                            "utf-8", errors="replace"
                        )[:500]

            parts = [
                f"\n{'─' * 60}",
                f"  {method}  {path}  →  {status}"
                f"  ({elapsed * 1000:.0f}ms)"
                f"  user={user}",
            ]
            if args:
                parts.append(f"  params   {args}")
            if req_body:
                parts.append(f"  req      {req_body}")
            if res_body:
                parts.append(f"  res      {res_body}")
            parts.append(f"{'─' * 60}")

            level = (
                logging.WARNING if status >= 400
                else logging.INFO
            )
            logger.log(level, "\n".join(parts))
            return response

        @self.before_serving
        async def services():
            """Initialize services before app is being served."""
            logger.warning("Initializing services...")

            await self.init_services()
            self.setup_metrics()

            if self.microservice_instance == Microservice.EVENTS:
                self.register_websocket_routes()

            self.register_routes()

            if self.microservice_instance.needs_rmq():
                self.RMQ = rmq.RMQBroker(self)
                await self.RMQ.start()
            
            # Start StreamMonitor for LIVESTREAM microservice
            if self.microservice_instance == Microservice.LIVESTREAM:
                logger.warning(f"LIVESTREAM microservice detected, checking for stream_monitor...")
                if hasattr(self, 'stream_monitor'):
                    logger.warning("stream_monitor found, starting...")
                    await self.stream_monitor.start()
                    logger.warning("stream_monitor.start() completed")
                else:
                    logger.error("stream_monitor attribute NOT FOUND on app instance!")

        @self.after_serving
        async def cleanup():
            """Cleanup resources after app is being stopped."""
            logger.warning("Cleaning up resources...")
            
            # Stop KPI background refresh loop
            if hasattr(self, '_kpi_aggregator'):
                self._kpi_aggregator.stop()
            
            # Stop StreamMonitor for LIVESTREAM microservice
            if self.microservice_instance == Microservice.LIVESTREAM:
                if hasattr(self, 'stream_monitor'):
                    await self.stream_monitor.stop()
            
            await self.clean_up()

    async def init_redis(self):
        """Initialize Redis connection with connection pooling"""
        try:
            logger.warning("Initializing Redis connection...")
            self.redis = Redis.from_url(
                os.environ["REDIS_URI"], 
                decode_responses=True, 
                encoding="utf-8",
                max_connections=5,  # Max connections per pod (reduced for Redis Cloud limits)
                socket_keepalive=True,
                health_check_interval=30,  # Check connection health every 30s
                retry_on_timeout=True,
                socket_connect_timeout=5
            )
            # Test connection
            await self.redis.ping()
            logger.info("Redis connection pool established")
            return self.redis
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
                logger.warning("Setting JWT secret...")
                await self.set_shared_secret()

            else:
                logger.warning("Getting JWT secret...")
                await self.get_shared_secret()

            logger.info("All services initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize services: {str(e)}", exc_info=True)
            raise

    async def set_shared_secret(self):
        """Set JWT secret in Redis if it doesn't exist"""
        if self.config["DEBUG"]:
            self.config["SECRET_KEY"] = "test-secret-key"
            self.config["JWT_SECRET_KEY"] = "test-secret-key"
            self.jwt = JWTManager(self)
            logger.info("JWT manager initialized in DEBUG mode")
            return

        try:
            # Check if secret already exists
            existing_secret = await self.redis.get("SECRET_KEY")
            if existing_secret:
                logger.warning("Using existing JWT secret from Redis")
                self.config["SECRET_KEY"] = existing_secret
            else:
                # Generate and set new secret
                logger.warning("Generating new JWT secret")
                self.config["SECRET_KEY"] = secrets.token_hex(32)
                await self.redis.set("SECRET_KEY", self.config["SECRET_KEY"])
                logger.warning("New JWT secret stored in Redis")

            # Set JWT secret key and initialize manager
            self.config["JWT_SECRET_KEY"] = self.config["SECRET_KEY"]
            self.jwt = JWTManager(self)
            logger.info("JWT manager initialized")

        except Exception as e:
            logger.error(f"Failed to handle JWT secret: {str(e)}", exc_info=True)
            raise

    async def get_shared_secret(self):
        """Get JWT secret from Redis"""

        if self.config["DEBUG"]:
            self.config["SECRET_KEY"] = "test-secret-key"
            self.config["JWT_SECRET_KEY"] = "test-secret-key"
            self.jwt = JWTManager(self)
            logger.info("JWT manager initialized in DEBUG mode")
            return
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
            logger.warning("Starting service cleanup process...")

            # Close SurrealDB connection
            if hasattr(self, "conn") and self.conn is not None:
                try:
                    logger.warning("Closing SurrealDB connection...")
                    # await self.conn._close_pools()
                    await self.pool_manager.close_all_pools()
                    logger.info("SurrealDB connection closed successfully")
                except Exception as db_close_error:
                    logger.error(
                        f"Error closing SurrealDB connection: {str(db_close_error)}",
                        exc_info=True,
                    )

            # Close Redis connection and connection pool
            if hasattr(self, "redis") and self.redis is not None:
                try:
                    logger.warning("Closing Redis connection pool...")
                    await self.redis.aclose()  # Close connection pool properly
                    logger.info("Redis connection pool closed successfully")
                except Exception as redis_close_error:
                    logger.error(
                        f"Error closing Redis connection: {str(redis_close_error)}",
                        exc_info=True,
                    )

            # Close RabbitMQ broker connection
            if hasattr(self, "RMQ") and self.RMQ is not None:
                try:
                    logger.warning("Closing RabbitMQ broker connection...")
                    await self.RMQ.close()
                    logger.info("RabbitMQ broker closed successfully")
                except Exception as rmq_close_error:
                    logger.error(
                        f"Error closing RabbitMQ connection: {str(rmq_close_error)}",
                        exc_info=True,
                    )

            logger.info("Service cleanup completed successfully")
        except Exception as general_error:
            logger.error(
                f"Unexpected error during service cleanup: {str(general_error)}",
                exc_info=True,
            )
            raise

    def setup_metrics(self):
        """
        Setup metrics collection for a Quart app
        """

        @self.before_serving
        async def register_metrics_endpoint():
            from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

            @self.route(f"/{self.microservice_instance.lower()}/metrics")
            async def metrics():
                return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}

            @self.route(f"/{self.microservice_instance.lower()}/conn")
            async def conn_stats():
                return (
                    await self.conn.pool.get_stats(),
                    200,
                    {"Content-Type": CONTENT_TYPE_LATEST},
                )

        @self.before_serving
        async def register_kpi_endpoints():
            from shared.kpi.aggregator import KPIAggregator
            from shared.kpi.views import kpis_handler, kpis_refresh_handler

            aggregator = KPIAggregator(
                pool=self.conn.pool,
                redis=self.redis,
                logger=self.logger,
                ttl=60,
            )
            self._kpi_aggregator = aggregator

            # Start background refresh loop (every 60s)
            await aggregator.start_background_loop(interval=60)

            # Register KPI endpoints only on auth service to avoid
            # route conflicts (e.g. users /{user_id}/ catch-all).
            if self.microservice_instance.lower() == "auth":
                self.add_url_rule("/auth/kpis", "kpis", kpis_handler, methods=["GET"])
                self.add_url_rule("/auth/kpis/refresh", "kpis_refresh", kpis_refresh_handler, methods=["POST"])
                logger.info("KPI endpoints registered at /auth/kpis")

        @self.before_request
        async def before_request():
            request.start_time = time.time()
            endpoint = request.path
            REQUESTS_IN_PROGRESS.labels(method=request.method, endpoint=endpoint).inc()

        @self.after_request
        async def after_request(response):
            endpoint = request.path
            resp_time = time.time() - getattr(request, 'start_time', time.time())
            REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(
                resp_time
            )
            REQUEST_COUNT.labels(
                method=request.method, endpoint=endpoint, status=response.status_code
            ).inc()
            REQUESTS_IN_PROGRESS.labels(method=request.method, endpoint=endpoint).dec()
            return response

    def register_routes(self):
        # Register routes
        logger.warning("Registering application routes...")
        self.views.register(self)

        logger.warning("Printing Application Routes...")
        logger.warning(self.url_map)

    def register_websocket_routes(self):
        """Register WebSocket routes"""

        # @self.websocket("/events/<event_id>/live/ws")
        @jwt_required
        async def event_live_updates(event_id: str):
            """Handle WebSocket connections for live event updates."""
            try:
                user_id = get_jwt_identity()

                # Verify user has access to this event
                event = await self.conn.fetch(event_id)
                if not event or (
                    event["host"]
                    != user_id
                    # or user_id not in [a["id"] for a in event.get("attendees", [])]
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
                        if self.redis:
                            await self.redis.delete(f"live_query:{event_id}")
                        logger.info(f"Cleaned up resources for event {event_id}")
                    except Exception as e:
                        logger.error(f"Cleanup error: {str(e)}", exc_info=True)

            except Exception as e:
                logger.error(f"Live updates error: {str(e)}", exc_info=True)
