from dataclasses import dataclass
from datetime import timedelta, datetime
from pprint import pprint
from http import HTTPStatus
from quart import make_response, render_template, current_app as app, request, jsonify
from quart_schema import validate_request, validate_response, document_querystring

from ..connectors import AuthDB
from shared.classful import route, QuartClassful

from quart_jwt_extended import create_access_token
from shared.notifications import NotificationManager
from redis.asyncio import Redis
from aiocache import cached, RedisCache, Cache
import os

import secrets
import logging

logger = logging.getLogger(__name__)


class BaseView(QuartClassful):

    def __init__(self):
        self.conn: AuthDB = app.conn
        self.redis: Redis = app.redis
        self.__notification_manager = NotificationManager()

    def generate_jwt_secret(self, identity):
        return create_access_token(identity=identity, expires_delta=timedelta(days=1))

    @route("/", methods=["GET"])
    async def index(self):
        return await self.healthcheck()

    @route("/auth/health", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def healthcheck(self):
        """SSS
        Simple health check endpoint that verifies service and dependency status.
        Returns 200 OK if everything is healthy, 503 Service Unavailable otherwise.
        """
        health_status = {
            "service": "microservices.auth",
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "dependencies": {"database": "unknown", "redis": "unknown"},
        }

        # Check database connection
        try:
            db_info = await self.conn._info()
            health_status["dependencies"]["database"] = "healthy"
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            health_status["dependencies"]["database"] = "unhealthy"
            health_status["status"] = "degraded"

        # Check Redis connection
        try:
            redis_ping = await self.redis.ping()
            health_status["dependencies"]["redis"] = (
                "healthy" if redis_ping else "unhealthy"
            )
            if not redis_ping:
                health_status["status"] = "degraded"
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            health_status["dependencies"]["redis"] = "unhealthy"
            health_status["status"] = "degraded"

        status_code = (
            HTTPStatus.OK
            if health_status["status"] == "healthy"
            else HTTPStatus.SERVICE_UNAVAILABLE
        )

        return jsonify(health_status), status_code

    @route("/auth/register", methods=["POST"])
    async def register_user(self):
        """
        Register a user account into the SurrealDB.
        """
        data = await request.get_json()
        created_acct = await self.conn._create_user(data)
        if not created_acct:
            return "Invalid Request Body or User already exists", HTTPStatus.CONFLICT
        try:
            await self.__n_register_user(created_acct)
            await self.__n_generate_otp(created_acct["id"], created_acct["email"])
        except Exception as e:
            logger.error(f"Registration error: {e}")
            raise
        created_acct["access_token"] = self.generate_jwt_secret(created_acct["id"])
        return jsonify(created_acct), HTTPStatus.CREATED

    @route("/auth/login", methods=["POST"])
    async def _login_user(self):
        """
        Verify user credentials
        """
        data = await request.get_json()
        if result := await self.conn._login(data):
            access_token = self.generate_jwt_secret(result["id"])
            await self.__notification_manager.recent_login_notification(
                user_id=result["id"],
                payload={
                    "ip_address": request.remote_addr,
                    "timeStamp": datetime.now().isoformat(),
                },
            )
            return (
                jsonify(access_token=access_token, token_type="bearer"),
                HTTPStatus.OK,
            )
        return "Bad username or password", HTTPStatus.UNAUTHORIZED

    async def __n_register_user(self, user_data: dict):
        """
        Register a new user and create Novu subscriber
        """
        try:

            # Create Novu subscriber
            return await self.__notification_manager.create_subscriber(
                user_id=user_data["id"],
                email=user_data["email"],
                first_name=user_data.get("first_name"),
                last_name=user_data.get("last_name"),
            )
        except Exception as e:
            logger.error(f"User registration error: {e}")
            raise

    async def __n_generate_otp(self, user_id: str, email: str):
        """
        Generate and send OTP for authentication
        """
        try:
            # Generate a 6-digit OTP
            otp = secrets.token_hex(3)[:6].upper()

            # Store OTP in Redis or your preferred storage with expiration
            await self.redis.set(f"otp:{user_id}", otp, ex=600)  # 10 minutes expiration

            # Send OTP via Novu
            await self.__notification_manager.send_otp_notification(
                user_id=user_id, otp=otp
            )

            return {"message": "OTP sent successfully"}
        except Exception as e:
            logger.error(f"OTP generation error: {e}")
            raise

    async def verify_otp(self, user_id: str, provided_otp: str):
        """
        Verify OTP for user authentication
        """
        try:
            # Retrieve stored OTP
            stored_otp = await self.redis.get(f"otp:{user_id}")

            if stored_otp and stored_otp == provided_otp:
                # Clear the OTP after successful verification
                await self.redis.delete(f"otp:{user_id}")
                return {"verified": True}

            return {"verified": False, "message": "Invalid OTP"}
        except Exception as e:
            logger.error(f"OTP verification error: {e}")
            raise
