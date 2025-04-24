from dataclasses import dataclass
from datetime import timedelta, datetime
from pprint import pprint
from http import HTTPStatus
from quart import make_response, render_template, current_app as app, request, jsonify

import uuid
from ..connectors import AuthDB
from shared.classful import route, QuartClassful

from quart_jwt_extended import create_access_token
import orjson as json
from shared.workers.brevo import Brevo
from shared.workers.novu import NotificationManager
from redis.asyncio import Redis
from redis.commands.json.path import Path
from typing import Optional, Dict
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
        self.__brevo_client = Brevo()

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

    @route("/leads", methods=["POST"])
    async def create_lead(self):
        """
        Create a new lead in the database.
        """
        data = await request.get_json()

        brevo_resp = await self.__brevo_client.create_contact(
            email=data.get("email"),
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
        )
        if not brevo_resp:
            return (
                "Failed to create lead in Brevo or Contact already exists.",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        created_lead = await self.conn._create_lead(
            data.get("email"), data.get("usecase")
        )
        if not created_lead:
            return "Invalid Request Body or Lead already exists", HTTPStatus.CONFLICT

        return (
            f"Created Lead {data.get('email')} in Brevo and SurrealDB",
            HTTPStatus.CREATED,
        )

    @route("/auth/verify", methods=["POST"])
    async def verify(self):
        """Verify a provided OTP."""
        data = await request.get_json()
        if not data.get("email") or not data.get("otp"):
            return "Invalid Request Body", HTTPStatus.BAD_REQUEST

        if result := await self.verify_otp(data.get("email"), data.get("otp")):
            await self.conn._verify_and_store(result)
            access_token = self.generate_jwt_secret(result["id"])
            return (
                jsonify(access_token=access_token, token_type="bearer"),
                HTTPStatus.OK,
            )
        return "Invalid OTP", HTTPStatus.UNAUTHORIZED

    @route("/auth/register", methods=["POST"])
    async def register_user(self):
        """
        Register a user account into the SurrealDB.
        """
        data = await request.get_json()
        data["id"] = str(uuid.uuid4())[:8]
        # created_acct = await self.conn._create_user(data)
        # Let's store the info pending in redis until they verify.

        # if not created_acct:
        #     return "Invalid Request Body or User already exists", HTTPStatus.CONFLICT
        try:
            await self.__n_register_user(
                email=data.get("email"), user_data=data, user_id=data["id"]
            )
        except Exception as e:
            logger.error(f"Registration error: {e}")
            raise

        if result := await self.__n_generate_otp(data["id"], data.get("email"), data):
            return result, HTTPStatus.CREATED
        else:
            return "Existing OTP, please verify", HTTPStatus.CONFLICT

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
                ip_address=request.remote_addr,
            )
            return (
                jsonify(access_token=access_token, token_type="bearer"),
                HTTPStatus.OK,
            )
        return "Bad username or password", HTTPStatus.UNAUTHORIZED

    async def __n_register_user(self, email: str, user_data: dict, user_id: str = None):
        """
        Create a new user in the Novu subscriber database.
        """
        try:

            # Create Novu subscriber
            return await self.__notification_manager.create_subscriber(
                email=email,
                first_name=user_data.get("first_name"),
                last_name=user_data.get("last_name"),
                user_id=user_id,
            )
        except Exception as e:
            logger.error(f"User registration error: {e}")
            raise

    async def __n_generate_otp(self, user_id: str, email: str, data: dict):
        """
        Generate and send OTP for authentication
        """
        try:
            # Generate a 6-digit OTP
            otp = secrets.token_hex(3)[:6].upper()

            # Check if otp already exists in redis
            existing_otp = await self.redis.get(f"otp:{email}")
            if existing_otp:
                return False

            # Store OTP in Redis or, and then store the temporary data
            key = f"otp:{email}"
            await self.redis.set(key, otp, ex=600)  # 10 minutes expiration

            await self.redis.set(
                f"users:pending:{email}", json.dumps(data), ex=800
            )  # Expire a little later

            # Send OTP via Novu
            await self.__notification_manager.send_otp_notification(
                user_id=user_id,
                ip_address=request.headers.get("REMOTE_ADDR")
                or request.headers.get("HTTP_X_FORWARDED_FOR")
                or request.headers.get("HTTP_X_REAL_IP")
                or request.remote_addr,
                otp=otp,
            )

            return otp
        except Exception as e:
            logger.error(f"OTP generation error: {e}")
            raise

    async def verify_otp(self, email: str, provided_otp: str) -> Optional[Dict]:
        """
        Verify OTP for user authentication
        """
        try:
            # Retrieve stored OTP
            stored_otp = await self.redis.get(f"otp:{email}")

            if stored_otp and stored_otp == provided_otp:
                # Clear the OTP after successful verification
                json_data = await self.redis.get(f"users:pending:{email}")
                json_data = json.loads(json_data)

                await self.redis.delete(f"otp:{email}")
                await self.redis.delete(f"users:pending:{email}")
                return json_data

            return {"verified": False, "message": "Invalid OTP"}
        except Exception as e:
            logger.error(f"OTP verification error: {e}")
            raise
