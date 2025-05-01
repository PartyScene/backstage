from dataclasses import dataclass
from datetime import timedelta, datetime
from http import HTTPStatus
from quart import make_response, render_template, current_app as app, request, jsonify
from quart_jwt_extended import create_access_token
from redis.asyncio import Redis
from typing import Optional, Dict
from aiocache import cached, RedisCache, Cache
import os
import secrets
import logging
import asyncio
import uuid_utils as ruuid
import orjson as json
from ..connectors import AuthDB
from shared.classful import route, QuartClassful
from shared.workers.brevo import Brevo
from shared.workers.novu import NotificationManager

logger = logging.getLogger(__name__)


class BaseView(QuartClassful):
    def __init__(self):
        self.conn: AuthDB = app.conn
        self.redis: Redis = app.redis
        self.__notification_manager = NotificationManager()
        self.__brevo_client = Brevo()

    def generate_jwt_secret(self, identity):
        """Generate a JWT secret for the given identity."""
        return create_access_token(identity=identity, expires_delta=timedelta(days=1))

    @route("/", methods=["GET"])
    async def index(self):
        """Return the healthcheck response."""
        return await self.healthcheck()

    @route("/auth/health", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def healthcheck(self):
        """Perform a health check on the service and its dependencies."""
        health_status = {
            "service": "microservices.auth",
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "dependencies": {"database": "unknown", "redis": "unknown"},
        }
        message = "Service is healthy"
        status_code = HTTPStatus.OK

        # Check database connection
        try:
            db_info = await self.conn._info()
            health_status["dependencies"]["database"] = "healthy"
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            health_status["dependencies"]["database"] = "unhealthy"
            health_status["status"] = "degraded"
            message = "Service degraded: Database connection failed"
            status_code = HTTPStatus.SERVICE_UNAVAILABLE


        # Check Redis connection
        try:
            redis_ping = await self.redis.ping()
            health_status["dependencies"]["redis"] = (
                "healthy" if redis_ping else "unhealthy"
            )
            if not redis_ping:
                health_status["status"] = "degraded"
                message = "Service degraded: Redis connection failed"
                status_code = HTTPStatus.SERVICE_UNAVAILABLE
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            health_status["dependencies"]["redis"] = "unhealthy"
            health_status["status"] = "degraded"
            message = "Service degraded: Redis connection failed"
            status_code = HTTPStatus.SERVICE_UNAVAILABLE


        return jsonify(data=health_status, message=message, status=status_code.phrase), status_code

    @route("/leads", methods=["POST"])
    async def create_lead(self):
        """Create a new lead in the database."""
        data = await request.get_json()

        brevo_resp = await self.__brevo_client.create_contact(
            email=data.get("email"),
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
        )
        if not brevo_resp:
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return jsonify(
                message="Failed to create lead in Brevo or Contact already exists.",
                status=status_code.phrase
            ), status_code


        created_lead = await self.conn._create_lead(
            data.get("email"), data.get("usecase")
        )
        if not created_lead:
            status_code = HTTPStatus.CONFLICT
            return jsonify(message="Invalid Request Body or Lead already exists", status=status_code.phrase), status_code

        status_code = HTTPStatus.CREATED
        return jsonify(
            message=f"Created Lead {data.get('email')} in Brevo and SurrealDB",
            status=status_code.phrase
        ), status_code

    @route("/auth/exists", methods=["GET"])
    async def check_exists(self):
        """Verify if a user with the provided parameter already exists."""
        type, param = request.args.get("type"), request.args.get("param")

        result = await self.conn._check_exists(param, type)

        if result:
            status_code = HTTPStatus.CONFLICT
            return jsonify(message="Already Exists.", status=status_code.phrase), status_code
        else:
            status_code = HTTPStatus.OK
            return jsonify(message="Available.", status=status_code.phrase), status_code

    @route("/auth/verify", methods=["POST"])
    async def verify(self):
        """Verify a provided OTP and generate an access token."""
        data = await request.get_json()
        if not data.get("email") or not data.get("otp"):
            status_code = HTTPStatus.BAD_REQUEST
            return jsonify(message="Invalid Request Body", status=status_code.phrase), status_code

        if result := await self.verify_otp(data.get("email"), data.get("otp")):
            await self.conn._verify_and_store(result)
            access_token = self.generate_jwt_secret(result["id"])
            status_code = HTTPStatus.OK
            return (
                jsonify(
                    data={"access_token": access_token, "token_type": "bearer"},
                    message="OTP verified successfully.",
                    status=status_code.phrase
                ),
                status_code,
            )
        status_code = HTTPStatus.UNAUTHORIZED
        return jsonify(message="Invalid OTP", status=status_code.phrase), status_code

    @route("/auth/register", methods=["POST"])
    async def register_user(self):
        """Register a user account into the SurrealDB."""
        data = await request.get_json()
        data["id"] = (
            str(ruuid.uuid4()).split("-")[-1]
            if not data.get("id", None)
            else data["id"]
        )

        try:
            result = await self.conn._check_exists(
                data["email"], "email"
            ) or await self.conn._check_exists(data["username"], "username")

            logger.debug("Result for Bloom Check %s" % result)
            if result:
                status_code = HTTPStatus.CONFLICT
                return jsonify(message="Credential Already Exists.", status=status_code.phrase), status_code

            await self.__n_register_user(
                email=data.get("email"), user_data=data, user_id=data["id"]
            )
        except Exception as e:
            logger.error(f"Registration error: {e}")
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            # Consider a more specific error response
            return jsonify(message="Registration failed due to an internal error.", status=status_code.phrase), status_code


        if otp_result := await self.__n_generate_otp(data["id"], data.get("email"), data):
            # Return the OTP only in dev/test environments for easier testing
            response_data = {}
            if os.getenv("ENVIRONMENT") in ["dev", "test"]:
                 response_data["otp"] = otp_result # Include OTP for testing

            status_code = HTTPStatus.CREATED
            return jsonify(data=response_data, message="User registered, OTP sent.", status=status_code.phrase), status_code
        else:
            status_code = HTTPStatus.CONFLICT
            return jsonify(message="Existing OTP, please verify", status=status_code.phrase), status_code

    @route("/auth/login", methods=["POST"])
    async def _login_user(self):
        """Verify user credentials and generate an access token."""
        data = await request.get_json()
        if result := await self.conn._login(data):
            access_token = self.generate_jwt_secret(result["id"])
            await self.__notification_manager.recent_login_notification(
                user_id=result["id"],
                ip_address=request.remote_addr,
            )
            status_code = HTTPStatus.OK
            return jsonify(
                data={"access_token": access_token, "token_type": "bearer"},
                message="Login successful.",
                status=status_code.phrase
            ), status_code

        status_code = HTTPStatus.UNAUTHORIZED
        return jsonify(message="Bad username or password", status=status_code.phrase), status_code

    async def __n_register_user(self, email: str, user_data: dict, user_id: str = None):
        """Create a new user in the Novu subscriber database."""
        try:
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
        """Generate and send OTP for authentication."""
        try:
            otp = secrets.token_hex(3)[:6].upper()

            existing_otp = await self.redis.get(f"otp:{email}")
            if existing_otp:
                return False

            key = f"otp:{email}"
            await self.redis.set(key, otp, ex=600)  # 10 minutes expiration

            await self.redis.set(
                f"users:pending:{email}", json.dumps(data), ex=800
            )  # Expire a little later

            await self.__notification_manager.send_otp_notification(
                user_id=user_id,
                ip_address=request.headers.get("REMOTE_ADDR")
                or request.headers.get("HTTP_X_FORWARDED_FOR")
                or request.headers.get("HTTP_X_REAL_IP")
                or request.remote_addr,  # type: ignore
                otp=otp,
            )

            return otp
        except Exception as e:
            logger.error(f"OTP generation error: {e}")
            raise

    async def verify_otp(self, email: str, provided_otp: str) -> Optional[Dict] | bool:
        """Verify OTP for user authentication."""
        try:
            stored_otp = await self.redis.get(f"otp:{email}")

            if stored_otp and stored_otp == provided_otp:
                json_data = await self.redis.get(f"users:pending:{email}")
                if not json_data: # Handle case where pending user data expired
                    return False
                json_data = json.loads(json_data)

                # Use asyncio.gather for concurrent deletion
                await asyncio.gather(
                    self.redis.delete(f"otp:{email}"),
                    self.redis.delete(f"users:pending:{email}")
                )
                return json_data

            return False
        except Exception as e:
            logger.error(f"OTP verification error: {e}")
            raise # Re-raise the exception after logging
