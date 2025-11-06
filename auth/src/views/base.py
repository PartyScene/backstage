from dataclasses import dataclass
from datetime import timedelta, datetime
from http import HTTPStatus
from quart import (
    current_app as app,
    request,
    jsonify,
    url_for,
)
from quart_jwt_extended import create_access_token
from quart_jwt_extended import jwt_required, get_jwt_identity
from redis.asyncio import Redis
from typing import Optional, Dict, Literal
from aiocache import cached, RedisCache, Cache
import os
import secrets
import logging
import asyncio
import uuid_utils as ruuid
import orjson as json

from auth.src.connectors import AuthDB
from shared.classful import route, QuartClassful
from shared.workers.brevo import Brevo
from shared.utils import veriff, get_client_ip
from shared.utils.apple_auth import AppleAuthClient
from shared.workers.novu import NotificationManager
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
import stripe
from stripe import StripeError

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "288617366843-b4uvkfpaqcavca7tcc9co7die2opu62k.apps.googleusercontent.com")
APPLE_CLIENT_ID = os.getenv("APPLE_CLIENT_ID", "com.scenesllc.partyscene")  # Your Apple app bundle ID or service ID
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")  # Use env vars for security


class BaseView(QuartClassful):
    def __init__(self):
        self.conn: AuthDB = app.conn
        self.redis: Redis = app.redis
        self.__notification_manager = NotificationManager()
        self.__brevo_client = Brevo()
        self.__veriff_client = veriff.VeriffClient()
        self.__apple_auth_client = AppleAuthClient()

    def generate_jwt_secret(self, identity):
        """Generate a JWT secret for the given identity."""
        return create_access_token(identity=identity, expires_delta=timedelta(days=180))

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

        return (
            jsonify(data=health_status, message=message, status=status_code.phrase),
            status_code,
        )

    @route("/leads", methods=["POST"])
    async def create_lead(self):
        """Create a new lead in the database."""
        data : dict = await request.get_json()

        brevo_resp = await self.__brevo_client.create_contact(
            email=data.get("email"),
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
        )
        if not brevo_resp:
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message="Failed to create lead in Brevo or Contact already exists.",
                    status=status_code.phrase,
                ),
                status_code,
            )

        created_lead = await self.conn._create_lead(
            data.get("email"), data.get("usecase")
        )
        if not created_lead:
            status_code = HTTPStatus.CONFLICT
            return (
                jsonify(
                    message="Invalid Request Body or Lead already exists",
                    status=status_code.phrase,
                ),
                status_code,
            )

        status_code = HTTPStatus.CREATED
        return (
            jsonify(
                message=f"Created Lead {data.get('email')} in Brevo and SurrealDB",
                status=status_code.phrase,
            ),
            status_code,
        )

    @route("/auth/forgot-password", methods=["POST"])
    async def forgot_password(self):
        """Request a password reset for a user."""
        data = await request.get_json()
        email = data.get("email")

        if not email:
            status_code = HTTPStatus.BAD_REQUEST
            return (
                jsonify(message="Email is required", status=status_code.phrase),
                status_code,
            )

        if not await self.conn._check_exists(email, "email"):
            status_code = HTTPStatus.NOT_FOUND
            return (
                jsonify(message="Email not found", status=status_code.phrase),
                status_code,
            )

        user_info = await self.conn._fetch_user_by_email(email)
        if not user_info:
            status_code = HTTPStatus.NOT_FOUND
            return (
                jsonify(message="User not found", status=status_code.phrase),
                status_code,
            )
        # Generate OTP and send it to the user
        otp = await self.__generate_and_send_otp(
            user_id=user_info["id"], email=email, data=data, context="forgot-password"
        )
        if otp:
            # Otp has been created, return success response
            status_code = HTTPStatus.OK
            # Return otp for testing purposes only
            if os.getenv("ENVIRONMENT") in ["dev", "test"]:
                return (
                    jsonify(
                        data={"otp": otp},
                        message="OTP sent to your email for password reset.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )

            return (
                jsonify(
                    message="OTP sent to your email for password reset.",
                    status=status_code.phrase,
                ),
                status_code,
            )
        else:
            # Otp already exists, return conflict response
            status_code = HTTPStatus.CONFLICT
            return (
                jsonify(
                    message="Existing OTP, please verify",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/auth/reset-password", methods=["POST"])
    async def reset_password(self):
        """Reset a user's password using the provided email and new password."""
        data = await request.get_json()
        email = data.get("email")
        new_password = data.get("new_password")
        otp = data.get("otp")
        if not email or not new_password or not otp:
            status_code = HTTPStatus.BAD_REQUEST

            return (
                jsonify(
                    message="Email, new password, and OTP are required",
                    status=status_code.phrase,
                ),
                status_code,
            )

        # Verify OTP before resetting password
        if not await self.verify_otp(
            email, otp, validate_only=True, context="forgot-password"
        ):
            status_code = HTTPStatus.UNAUTHORIZED
            return (
                jsonify(message="Invalid or expired OTP", status=status_code.phrase),
                status_code,
            )

        if await self.conn._reset_password(email, new_password):
            status_code = HTTPStatus.OK
            return (
                jsonify(
                    message="Password reset successfully", status=status_code.phrase
                ),
                status_code,
            )
        else:
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(message="Failed to reset password", status=status_code.phrase),
                status_code,
            )

    @route("/auth/exists", methods=["GET"])
    async def check_exists(self):
        """Verify if a user with the provided parameter already exists."""
        type, param = request.args.get("type", ""), request.args.get("param")

        if type in ("email", "username"):
            result = await self.conn._check_exists(param, type)
        else:
            result = None

        if result:
            status_code = HTTPStatus.CONFLICT
            return (
                jsonify(message="Already Exists.", status=status_code.phrase),
                status_code,
            )
        else:
            status_code = HTTPStatus.OK
            return jsonify(message="Available.", status=status_code.phrase), status_code

    @route("/auth/verify", methods=["POST"])
    async def verify(self):
        """Verify a provided OTP and generate an access token."""
        data = await request.get_json()

        # If context is forgot password, we're probably only validating
        context = data.get("context", None)
        validate_only = context in (
            "forgot-password",
        )  # If context is forgot-password, we only validate the OTP
        delete = (
            context != "forgot-password"
        )  # If context is forgot-password, we don't delete the OTP after verification

        print("Verify OTP Data %s" % data)
        if not data.get("email") or not data.get("otp") or not context:
            status_code = HTTPStatus.BAD_REQUEST
            return (
                jsonify(message="Invalid Request Body", status=status_code.phrase),
                status_code,
            )

        if result := await self.verify_otp(
            data.get("email"),
            data.get("otp"),
            validate_only=validate_only,
            context=context,
            delete=delete,
        ):
            # If validate_only is True, we only return the boolean result
            print("Verify OTP Result %s" % result)
            if validate_only:
                status_code = HTTPStatus.OK
                return (
                    jsonify(
                        message="OTP verified successfully", status=status_code.phrase
                    ),
                    status_code,
                )

            if isinstance(result, dict):
                await self.conn._store_after_verify(result)
                access_token = self.generate_jwt_secret(result["id"])
                status_code = HTTPStatus.OK
                return (
                    jsonify(
                        data={"access_token": access_token, "token_type": "bearer"},
                        message="OTP verified successfully.",
                        status=status_code.phrase,
                    ),
                    status_code,
                )
        else:
            status_code = HTTPStatus.UNAUTHORIZED
            return (
                jsonify(message="Invalid OTP", status=status_code.phrase),
                status_code,
            )

    @route("/auth/register", methods=["POST"])
    async def register_user(self):
        """Register a user account into the SurrealDB."""
        data = await request.get_json()
        
        # Check if there's an existing Novu subscriber for this email
        existing_subscriber = await self.__notification_manager.get_subscriber_by_email(data.get("email"))
        if existing_subscriber:
            logger.warning("User already exists in Novu, reusing subscriber_id %s for user %s", existing_subscriber.subscriber_id, data.get("email"))
            # Reuse the existing subscriber_id as user_id
            data["id"] = existing_subscriber.subscriber_id
        else:
            # Generate a random ID if none is provided and no existing subscriber
            data["id"] = (
                str(ruuid.uuid4()).split("-")[-1]
                if not data.get("id", None)
                else data["id"]
            )

        try:
            # Fast cuckoo filter check first for email existence
            email_exists = await self.conn._check_exists(data["email"], "email")
            
            # Check if username is taken (separate check)
            username_exists = await self.conn._check_exists(data["username"], "username")
            
            if email_exists:
                # Only fetch full user data if cuckoo filter indicates existence
                existing_user = await self.conn._fetch_user(data["email"], "email")
                if not existing_user:
                    # Cuckoo filter false positive - user doesn't actually exist
                    logger.warning(f"Cuckoo filter false positive for email: {data['email']}")
                else:
                    # User exists - check their auth provider to give specific guidance
                    auth_provider = existing_user.get("auth_provider", "")
                    logger.debug(f"User {data['email']} already exists with auth_provider: {auth_provider}")
                    
                    if auth_provider == "google":
                        message = "This email is already registered with Google Sign-In. Please use Google Sign-In to log in."
                        error_code = "MUST_USE_GOOGLE_SSO"
                    elif auth_provider == "apple":  
                        message = "This email is already registered with Apple Sign-In. Please use Apple Sign-In to log in."
                        error_code = "MUST_USE_APPLE_SSO"
                    elif auth_provider and auth_provider != "password":
                        message = f"This email is already registered with {auth_provider.title()} Sign-In. Please use {auth_provider.title()} Sign-In to log in."
                        error_code = "MUST_USE_SSO"
                    else:
                        message = "This email is already registered. Please log in instead."
                        error_code = "EMAIL_EXISTS"
                    
                    status_code = HTTPStatus.CONFLICT
                    return (
                        jsonify(
                            message=message,
                            error_code=error_code,
                            status=status_code.phrase
                        ),
                        status_code,
                    )
            elif username_exists:
                # Username taken (but email is available)
                status_code = HTTPStatus.CONFLICT
                return (
                    jsonify(
                        message="Username already taken. Please choose a different username.",
                        error_code="USERNAME_EXISTS", 
                        status=status_code.phrase
                    ),
                    status_code,
                )

            await self.__n_register_user(
                email=data.get("email"), user_data=data, user_id=data["id"]
            )
        except Exception as e:
            logger.error(f"Registration error: {e}")
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            # Consider a more specific error response
            return (
                jsonify(
                    message="Registration failed due to an internal error.",
                    status=status_code.phrase,
                ),
                status_code,
            )

        if otp_result := await self.__generate_and_send_otp(
            data["id"], data.get("email"), data, context="register"
        ):
            # Return the OTP only in dev/test environments for easier testing
            response_data = {}
            if os.getenv("ENVIRONMENT") in ["dev", "test"]:
                response_data["otp"] = otp_result  # Include OTP for testing

            status_code = HTTPStatus.CREATED
            return (
                jsonify(
                    data=response_data,
                    message="User registered, OTP sent.",
                    status=status_code.phrase,
                ),
                status_code,
            )
        else:
            status_code = HTTPStatus.CONFLICT
            return (
                jsonify(
                    message="Existing OTP, please verify", status=status_code.phrase
                ),
                status_code,
            )

    @route("/auth/kyc/update", methods=["POST", "PATCH"])
    @jwt_required
    async def update_kyc_status(self):
        """Update the KYC status of the user."""
        user_id = get_jwt_identity()
        data = await request.get_json()
        status = data.get("kyc_status", "false") == "true"
        updated_data = {
            "kyc_status": status,
            "id": user_id,
        }
        if await self.conn.update_user(updated_data):
            status_code = HTTPStatus.OK
            return (
                jsonify(
                    message="KYC Data updated successfully.", status=status_code.phrase
                ),
                status_code,
            )

    @route("/auth/kyc/session", methods=["POST"])
    @jwt_required
    async def create_kyc_session(self):
        """"""
        veriff_resp = await self.__veriff_client.create_session(user_id=get_jwt_identity())
        if not veriff_resp:
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message="Failed to create session in Veriff.",
                    status=status_code.phrase,
                ),
                status_code,
            )

        status_code = HTTPStatus.CREATED
        return (
            jsonify(
                message=f"Veriff session created.",
                data=veriff_resp,
                status=status_code.phrase,
            ),
            status_code,
        )

    @route("/auth/login", methods=["POST"])
    async def login_user(self):
        """Verify user credentials and generate an access token."""
        data = await request.get_json()
        result = await self.conn._login(data)
        
        # Handle SSO blocking responses
        if isinstance(result, str):
            if result == "use_google":
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="This account was created with Google Sign-In. Please use Google Sign-In to log in.",
                        error_code="MUST_USE_GOOGLE_SSO",
                        status=status_code.phrase
                    ),
                    status_code,
                )
            elif result == "use_apple":
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="This account was created with Apple Sign-In. Please use Apple Sign-In to log in.",
                        error_code="MUST_USE_APPLE_SSO",
                        status=status_code.phrase
                    ),
                    status_code,
                )
            elif result == "use_sso":
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="This account was created with social sign-in. Please use social sign-in to log in.",
                        error_code="MUST_USE_SSO",
                        status=status_code.phrase
                    ),
                    status_code,
                )
        
        # Handle successful password login
        if result and isinstance(result, dict):
            access_token = self.generate_jwt_secret(result["id"])
            await self.__notification_manager.recent_login_notification(
                user_id=result["id"],
                ip_address=get_client_ip(request),
            )
            status_code = HTTPStatus.OK
            return (
                jsonify(
                    data={"access_token": access_token, "token_type": "bearer"},
                    message="Login successful.",
                    status=status_code.phrase,
                ),
                status_code,
            )

        # Handle failed login (None result)
        status_code = HTTPStatus.UNAUTHORIZED
        return (
            jsonify(message="Bad username or password", status=status_code.phrase),
            status_code,
        )

    async def __n_register_user(self, email: str, user_data: dict, user_id: str = ""):
        """Create a new user in the Novu subscriber database."""
        try:
            return await self.__notification_manager.create_subscriber(
                email=email,
                first_name=user_data.get("organization_name") or user_data.get("username") or user_data.get("first_name"),
                last_name=user_data.get("last_name"),
                user_id=user_id,
            )
        except Exception as e:
            logger.error(f"User registration error: {e}")
            raise

    @route("/auth/google", methods=["POST"])
    async def auth_google(self):
        data = await request.get_json()
        token_str = data.get("id_token")

        if not token_str:
            status_code = HTTPStatus.BAD_REQUEST
            return (
                jsonify(message="Missing ID token", status=status_code.phrase),
                status_code,
            )

        # try:
        # Verify the token
        idinfo = id_token.verify_oauth2_token(
            token_str, grequests.Request(), GOOGLE_CLIENT_ID
        )

        # Optional: check email is verified
        if not idinfo.get("email_verified"):
            return jsonify({"error": "Email not verified"}), 403

        # Extract user info
        user_id = idinfo["sub"]  # Google unique ID
        email = idinfo["email"]
        first_name = idinfo.get("given_name")
        last_name = idinfo.get("family_name")
        picture = idinfo.get("picture")

        # Check if there's an existing Novu subscriber for this email
        existing_subscriber = await self.__notification_manager.get_subscriber_by_email(email)
        novu_user_id = None
        if existing_subscriber:
            logger.info(f"Existing Novu subscriber found for {email}, reusing subscriber_id {existing_subscriber.subscriber_id}")
            novu_user_id = existing_subscriber.subscriber_id

        # Robust SSO: Try to create user, handle existing gracefully
        user_data = {
            "google_sub": user_id,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "avatar": picture,
            "auth_provider": "google",
        }
        
        # If we have an existing Novu subscriber, use that ID for the user
        if novu_user_id:
            user_data["id"] = novu_user_id
        
        # Use robust sso_store - handles duplicates and account linking automatically
        created_or_existing_user = await self.conn.sso_store(user_data)
        
        if not created_or_existing_user:
            logger.error(f"SSO store failed for Google user: {email}")
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message="Authentication failed, please try again",
                    status=status_code.phrase
                ),
                status_code,
            )
        
        # Check if this was a new user (created) or existing user (fetched)
        try:
            # For new users, register with notification service
            if not existing_subscriber:
                await self.__n_register_user(
                    email=email,
                    user_data=created_or_existing_user,
                    user_id=created_or_existing_user["id"]
                )
                message = "User registered successfully, proceed to update username."
                status_code = HTTPStatus.CREATED
            else:
                message = "Login successful."
                status_code = HTTPStatus.OK
        except Exception as notification_error:
            logger.warning(f"Notification service error for {email}: {notification_error}")
            # Don't fail the auth flow for notification issues
            message = "Login successful."
            status_code = HTTPStatus.OK
        
        # Generate JWT token
        access_token = self.generate_jwt_secret(created_or_existing_user["id"])
        
        # Send recent login notification for all SSO logins (new and existing users)
        try:
            await self.__notification_manager.recent_login_notification(
                user_id=created_or_existing_user["id"],
                ip_address=get_client_ip(request),
            )
        except Exception as login_notif_error:
            logger.warning(f"Recent login notification failed for {email}: {login_notif_error}")
        
        return (
            jsonify(
                data={"access_token": access_token, "token_type": "bearer"},
                message=message,
                status=status_code.phrase,
            ),
            status_code,
        )

        # except ValueError:
        #     # Invalid token
        #     logger.error("Invalid ID token")
        #     status_code = HTTPStatus.UNAUTHORIZED
        #     return (
        #         jsonify(message="Invalid ID token", status=status_code.phrase),
        #         status_code,
        #     )

    @route("/auth/apple", methods=["POST"])
    async def auth_apple(self):
        """
        Authenticate user with Apple Sign In.
        
        Expects JSON payload with:
        - identity_token: JWT identity token from Apple Sign In
        - user (optional): User info (only provided on first sign in)
          {
              "name": {"firstName": "John", "lastName": "Doe"},
              "email": "user@privaterelay.appleid.com"
          }
        
        Returns:
            JSON response with access token
        """
        data = await request.get_json()
        identity_token = data.get("identity_token")
        user_info = data.get("user")  # Only provided on first sign in
        
        if not identity_token:
            status_code = HTTPStatus.BAD_REQUEST
            return (
                jsonify(message="Missing identity token", status=status_code.phrase),
                status_code,
            )
        
        if not APPLE_CLIENT_ID:
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message="Apple Sign In not configured",
                    status=status_code.phrase
                ),
                status_code,
            )
        
        try:
            # Verify the identity token with Apple's public keys
            # For development/testing: set APPLE_DEV_MODE=true to skip verification
            is_dev_mode = os.getenv("APPLE_DEV_MODE", "false").lower() == "true"
            
            if is_dev_mode:
                logger.warning("Apple Sign In running in DEV MODE - Token verification SKIPPED")
                decoded_token = await self.__apple_auth_client.verify_identity_token_unverified(
                    identity_token
                )
            else:
                decoded_token = await self.__apple_auth_client.verify_identity_token(
                    identity_token,
                    client_id=APPLE_CLIENT_ID
                )
            
            # Extract user information from token
            apple_user_id = decoded_token["sub"]  # Apple unique ID
            email = decoded_token.get("email")
            email_verified = decoded_token.get("email_verified", False)  # Apple emails are verified
            
            # Check if email verification is required
            if not email_verified:
                status_code = HTTPStatus.FORBIDDEN
                return (
                    jsonify(
                        message="Email not verified",
                        status=status_code.phrase
                    ),
                    status_code,
                )
            
            # Extract name from user info if provided (only on first sign in)
            first_name = None
            last_name = None
            if user_info and "name" in user_info:
                first_name = user_info["name"].get("firstName")
                last_name = user_info["name"].get("lastName")
            
            # Check if there's an existing Novu subscriber for this email
            existing_subscriber = await self.__notification_manager.get_subscriber_by_email(email)
            novu_user_id = None
            if existing_subscriber:
                logger.info(f"Existing Novu subscriber found for {email}, reusing subscriber_id {existing_subscriber.subscriber_id}")
                novu_user_id = existing_subscriber.subscriber_id
            
            # Robust Apple SSO: Always use sso_store for consistent handling
            user_data = {
                "apple_sub": apple_user_id,
                "email": email,
                "first_name": first_name or "",
                "last_name": last_name or "",
                "auth_provider": "apple",
            }
            
            # If we have an existing Novu subscriber, use that ID for the user
            if novu_user_id:
                user_data["id"] = novu_user_id
            
            # Use robust sso_store - handles duplicates and account linking automatically
            created_or_existing_user = await self.conn.sso_store(user_data)
            
            if not created_or_existing_user:
                logger.error(f"SSO store failed for Apple user: {email}")
                status_code = HTTPStatus.INTERNAL_SERVER_ERROR
                return (
                    jsonify(
                        message="Authentication failed, please try again",
                        status=status_code.phrase
                    ),
                    status_code,
                )
            
            # Check if this was a new user or existing user for appropriate messaging
            try:
                if not existing_subscriber:
                    # New user - register with notification service
                    await self.__n_register_user(
                        email=email,
                        user_data=created_or_existing_user,
                        user_id=created_or_existing_user["id"]
                    )
                    message = "User registered successfully, proceed to update username."
                    status_code = HTTPStatus.CREATED
                else:
                    message = "Login successful."
                    status_code = HTTPStatus.OK
            except Exception as notification_error:
                logger.warning(f"Notification service error for {email}: {notification_error}")
                # Don't fail the auth flow for notification issues
                message = "Login successful."
                status_code = HTTPStatus.OK
            
            # Generate JWT token
            access_token = self.generate_jwt_secret(created_or_existing_user["id"])
            
            # Send recent login notification for all SSO logins (new and existing users)
            try:
                await self.__notification_manager.recent_login_notification(
                    user_id=created_or_existing_user["id"],
                    ip_address=get_client_ip(request),
                )
            except Exception as login_notif_error:
                logger.warning(f"Recent login notification failed for {email}: {login_notif_error}")
            
            return (
                jsonify(
                    data={"access_token": access_token, "token_type": "bearer"},
                    message=message,
                    status=status_code.phrase,
                ),
                status_code,
            )
        
        except jwt.ExpiredSignatureError:
            logger.warning(f"Expired Apple token attempted from {get_client_ip()}")
            status_code = HTTPStatus.UNAUTHORIZED
            return (
                jsonify(
                    message="Apple token has expired, please sign in again",
                    status=status_code.phrase
                ),
                status_code,
            )
            
        except jwt.InvalidAudienceError:
            logger.error("Invalid audience in Apple token - client ID mismatch")
            status_code = HTTPStatus.UNAUTHORIZED
            return (
                jsonify(
                    message="Invalid Apple token configuration",
                    status=status_code.phrase
                ),
                status_code,
            )
            
        except jwt.InvalidIssuerError:
            logger.error("Invalid issuer in Apple token - not from Apple")
            status_code = HTTPStatus.UNAUTHORIZED
            return (
                jsonify(
                    message="Invalid Apple token source",
                    status=status_code.phrase
                ),
                status_code,
            )
            
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid Apple token from {get_client_ip()}: {e}")
            status_code = HTTPStatus.UNAUTHORIZED
            return (
                jsonify(
                    message="Invalid or malformed Apple token",
                    status=status_code.phrase
                ),
                status_code,
            )
            
        except Exception as e:
            logger.error(f"Unexpected error during Apple Sign In: {e}")
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message="Authentication service temporarily unavailable",
                    status=status_code.phrase
                ),
                status_code,
            )

    @route("/auth/create-stripe-account", methods=["POST"])
    @jwt_required
    async def create_stripe_account(self):
        data = await request.json
        user_id = get_jwt_identity()
        user_country = data.get("country", "US")  # Default to US
        
        # Get user email
        user_email = await self.conn.decrypt_credentials(user_id)
        try:
            # Create Express account
            account = await stripe.Account.create_async(
                type="express",
                country=user_country,
                email=user_email,
                capabilities={
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
                business_type="individual",  # Or 'company'; adjust based on user
            )

            app.logger.warning("%s | %s  | %s | %s", user_id, user_email, account.id, account)
            app.logger.warning("Attempting to update user with stripe account id %s", account.id)
            
            # Store account.id in your DB for this user
            await self.conn.update_user(
                {"id": user_id, "stripe_account_id": account.id}
            )

            # Create onboarding link
            account_link = await stripe.AccountLink.create_async(
                account=account.id,
                refresh_url=url_for(
                    ".reauth_stripe", account_id=account.id, _external=True
                ).replace("http://", "https://"),  # Force HTTPS for Stripe livemode
                return_url=url_for(
                    ".stripe_return", account_id=account.id, _external=True
                ).replace("http://", "https://"),  # Force HTTPS for Stripe livemode
                type="account_onboarding",
            )

            status_code = HTTPStatus.OK
            return (
                jsonify(url=account_link.url),
                status_code,
            )  # Frontend redirects to this URL
        except StripeError as e:
            status_code = HTTPStatus.BAD_REQUEST
            return jsonify(error=str(e)), status_code

    @route("/auth/stripe-return", methods=["GET"])
    async def stripe_return(self):
        # User completed (or exited) onboarding
        account_id = request.args.get(
            "account_id"
        )  # Retrieve from your session or DB (pass via state if needed)
        app.logger.warning("JWT Identity may not exist")
        app.logger.warning(get_jwt_identity())
        
        user = await self.conn._fetch_user(account_id, "stripe_account_id")

        if not user:
            return jsonify(message="User not found", status=HTTPStatus.NOT_FOUND.phrase), HTTPStatus.NOT_FOUND
        
        account = await stripe.Account.retrieve_async(account_id)

        app.logger.warning("%s | %s | %s", user["id"], account.id, account)
        app.logger.warning("Attempting to update user with stripe account id %s", account.id)

        await self.conn.update_user(
            {"id": user["id"], "stripe_account_kyc_status": True}
        )
        return jsonify(message="onboarding success"), HTTPStatus.OK

    @route("/auth/reauth-stripe", methods=["GET"])
    async def reauth_stripe(self):
        """
        Regenerate a new Stripe account link if the previous one has expired.
        
        Returns:
            tuple: A tuple containing (response, status_code) where response is a JSON object
            with the new account link URL and status_code is HTTP 200 OK.
        
        Raises:
            StripeError: If there is an error creating the new account link.
        """
        account_id = request.args.get("account_id")  # Retrieve from your session or DB
        # Regenerate a new link if expired
        account_link = await stripe.AccountLink.create_async(
            account=account_id,
            refresh_url=url_for(".reauth_stripe", account_id=account_id, _external=True).replace("http://", "https://"),
            return_url=url_for(".stripe_return", account_id=account_id, _external=True).replace("http://", "https://"),
            type="account_onboarding",
        )
        return jsonify(url=account_link.url), HTTPStatus.OK

    async def __generate_and_send_otp(
        self,
        user_id: str,
        email: str,
        data: Optional[dict],
        context: Literal["register", "forgot-password"],
    ) -> str | bool:
        """Generate and send OTP for authentication
        If data is provided, it will be stored in Redis for later verification.
        If an OTP already exists for the email, it will return False.
        Args:
            user_id (str): The ID of the user.
            email (str): The email address of the user.
            data (Optional[dict]): Additional data to store for later verification.
        Returns:
            str | bool: The generated OTP if successful, False if an OTP already exists.
        """
        try:
            otp = secrets.token_hex(3)[:6].upper()
            key = f"{context}-otp:{email}"
            # Check if an OTP already exists for this email
            existing_otp = await self.redis.get(key)
            if existing_otp:
                return False
            # Store the OTP in Redis with a 10-minute expiration
            await self.redis.set(key, otp, ex=600)  # 10 minutes expiration

            if data:
                # Store user data in Redis for later verification
                await self.redis.set(
                    f"users:pending:{email}", json.dumps(data), ex=800
                )  # Expire a little later
            
            await self.__notification_manager.send_otp_notification(
                user_id=user_id,
                ip_address=get_client_ip(request),
                otp=otp,
            )

            return otp
        except Exception as e:
            logger.error(f"OTP generation error: {e}")
            raise

    
    @route("/auth/veriff-webhook", methods=["POST"])
    async def veriff_webhook(self):
        raw_body = await request.get_data()  # Raw bytes for signature verification
        # received_signature = request.headers.get("X-HMAC-SIGNATURE")

        # # Verify signature
        # expected_signature = hmac.new(VERIFF_SECRET, raw_body, hashlib.sha256).hexdigest()
        # if not hmac.compare_digest(expected_signature, received_signature):
        #     return jsonify({"error": "Invalid signature"}), 403

        data = await request.json

        # Process the decision (e.g., update user status in DB)
        user_id = data.get("verification").get("vendorData")
        status = data.get("verification").get("decision").get("status")
        if status == "approved":
            # Mark user as verified
            await self.conn.update_user({"id": user_id, "kyc_status": True})
        elif status == "declined":
            # Handle rejection
            await self.conn.update_user({"id": user_id, "kyc_status": False})

        return jsonify({"status": "received"}), 200

    @route("/auth/account", methods=["DELETE"])
    @jwt_required
    async def delete_account(self):
        """
        Schedule account deletion with a 30-day grace period.
        
        The account will be marked for deletion and actually deleted after 30 days.
        During this period, users can cancel the deletion request.
        
        Returns:
            JSON response confirming deletion scheduling
        """
        user_id = get_jwt_identity()
        
        try:
            # Check if user already has a scheduled deletion
            user_data = await self.conn.pool.execute_query(
                "SELECT scheduled_deletion_at FROM type::thing('users', $user_id);",
                {"user_id": user_id}
            )
            
            if not user_data or not user_data[0]:
                status_code = HTTPStatus.NOT_FOUND
                return (
                    jsonify(message="User not found", status=status_code.phrase),
                    status_code,
                )
            
            # Check if deletion is already scheduled
            if user_data[0].get("scheduled_deletion_at"):
                status_code = HTTPStatus.CONFLICT
                return (
                    jsonify(
                        message="Account deletion already scheduled",
                        data={"scheduled_deletion_at": user_data[0].get("scheduled_deletion_at")},
                        status=status_code.phrase
                    ),
                    status_code,
                )
            
            # Schedule deletion for 30 days from now
            deletion_date = datetime.now() + timedelta(days=30)
            
            # Update user record with scheduled deletion date
            await self.conn.pool.execute_query(
                "UPDATE type::thing('users', $user_id) SET scheduled_deletion_at = time::now() + 30d;",
                {"user_id": user_id}
            )


            # Send notification about scheduled deletion
            try:
                
                
                # You can add a notification workflow for deletion scheduling
                logger.info(f"Scheduled account deletion for {user_id} at {deletion_date}")
            except Exception as e:
                logger.warning(f"Failed to send deletion notification: {e}")
            
            status_code = HTTPStatus.OK
            return (
                jsonify(
                    message="Account deletion scheduled. You have 30 days to cancel.",
                    data={
                        "scheduled_deletion_at": deletion_date.isoformat(),
                        "days_remaining": 30
                    },
                    status=status_code.phrase
                ),
                status_code,
            )
        
        except Exception as e:
            logger.error(f"Account deletion scheduling error for user {user_id}: {e}")
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message="An error occurred while scheduling account deletion",
                    status=status_code.phrase
                ),
                status_code,
            )
    
    @route("/auth/account/cancel-deletion", methods=["POST"])
    @jwt_required
    async def cancel_account_deletion(self):
        """
        Cancel a scheduled account deletion.
        
        Users can cancel their deletion request within the 30-day grace period.
        
        Returns:
            JSON response confirming cancellation
        """
        user_id = get_jwt_identity()
        
        try:
            # Check if user has a scheduled deletion
            user_data = await self.conn.pool.execute_query(
                "SELECT scheduled_deletion_at FROM type::thing('users', $user_id);",
                {"user_id": user_id}
            )
            
            if not user_data or not user_data:
                status_code = HTTPStatus.NOT_FOUND
                return (
                    jsonify(message="User not found", status=status_code.phrase),
                    status_code,
                )
            
            # Check if deletion is scheduled
            if not user_data.get("scheduled_deletion_at"):
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="No scheduled deletion to cancel",
                        status=status_code.phrase
                    ),
                    status_code,
                )
            
            # Cancel the scheduled deletion
            await self.conn.pool.execute_query(
                "UPDATE type::thing('users', $user_id) SET scheduled_deletion_at = NONE;",
                {"user_id": user_id}
            )
            
            logger.info(f"Cancelled scheduled deletion for user {user_id}")
            
            status_code = HTTPStatus.OK
            return (
                jsonify(
                    message="Account deletion cancelled successfully",
                    status=status_code.phrase
                ),
                status_code,
            )
        
        except Exception as e:
            logger.error(f"Cancellation error for user {user_id}: {e}")
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message="An error occurred while cancelling deletion",
                    status=status_code.phrase
                ),
                status_code,
            )
    
    async def verify_otp(
        self,
        email: str,
        provided_otp: str,
        validate_only: Optional[bool],
        context: Literal["register", "forgot-password"],
        delete: bool = True,
    ) -> Optional[Dict] | bool:
        """Verify and delete OTP for authentication.
        Args:
            email (str): The email address of the user.
            provided_otp (str): The OTP provided by the user.
            validate_only (Optional[bool]): If True, only validate the OTP without deleting or returning user data.
        Returns:
            Optional[Dict] | bool: User data if OTP is valid, False if invalid or expired.
        """
        try:
            key = f"{context}-otp:{email}"
            stored_otp = await self.redis.get(key)

            if stored_otp and stored_otp == provided_otp:
                if validate_only:
                    print("Validate only %s" % validate_only)
                    print("Delete %s" % delete)
                    # Delete OTP from Redis
                    if delete:
                        await self.redis.delete(key)
                    return True

                # If validate_only is True, we still need to fetch user data
                json_data = await self.redis.get(f"users:pending:{email}")
                if not json_data:  # Handle case where pending user data expired
                    return False
                json_data = json.loads(json_data)

                # Use asyncio.gather for concurrent deletion
                if delete:
                    await asyncio.gather(
                        self.redis.delete(key),
                        self.redis.delete(f"users:pending:{email}"),
                    )
                return json_data

            return False
        except Exception as e:
            logger.error(f"OTP verification error: {e}")
            raise  # Re-raise the exception after logging
