from dataclasses import dataclass
from datetime import timedelta, datetime
from http import HTTPStatus
from quart import (
    current_app as app,
    request,
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
from shared.middleware import rate_limit, GlobalRateLimits
from shared.workers.brevo import Brevo
from shared.utils import veriff, get_client_ip, api_response, api_error
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

        return api_response(message, status_code, data=health_status)

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
            return api_error(
                "Failed to create lead in Brevo or Contact already exists.",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

        created_lead = await self.conn._create_lead(
            data.get("email"), data.get("usecase")
        )
        if not created_lead:
            return api_error(
                "Invalid Request Body or Lead already exists",
                HTTPStatus.CONFLICT
            )

        return api_response(
            f"Created Lead {data.get('email')} in Brevo and SurrealDB",
            HTTPStatus.CREATED
        )

    @route("/auth/forgot-password", methods=["POST"])
    @rate_limit(**GlobalRateLimits.OTP_LIMITS)
    async def forgot_password(self):
        """Request a password reset for a user."""
        data = await request.get_json()
        email = data.get("email")

        if not email:
            return api_error("Email is required", HTTPStatus.BAD_REQUEST)

        if not await self.conn._check_exists(email, "email"):
            return api_error("Email not found", HTTPStatus.NOT_FOUND)

        user_info = await self.conn._fetch_user_by_email(email)
        if not user_info:
            return api_error("User not found", HTTPStatus.NOT_FOUND)
        # Generate OTP and send it to the user
        await self.__notification_manager.create_subscriber(
                email=email,
                first_name=user_info.get("organization_name") or user_info.get("username") or user_info.get("first_name"),
                last_name=user_info.get("last_name"),
                user_id=user_info["id"],
            )
        otp = await self.__generate_and_send_otp(
            user_id=user_info["id"],
            email=email, 
            data=data, 
            ip_address=get_client_ip(request),
            context="forgot-password"
        )
        if otp:
            # Otp has been created, return success response
            status_code = HTTPStatus.OK
            # Return otp for testing purposes only
            if os.getenv("ENVIRONMENT") in ["dev", "test"]:
                return api_response(
                    "OTP sent to your email for password reset.",
                    HTTPStatus.OK,
                    data={"otp": otp}
                )

            return api_response(
                "OTP sent to your email for password reset.",
                HTTPStatus.OK
            )
        else:
            # Otp already exists, return conflict response
            return api_error(
                "Existing OTP, please verify",
                HTTPStatus.CONFLICT
            )

    @route("/auth/reset-password", methods=["POST"])
    async def reset_password(self):
        """Reset a user's password using the provided email and new password."""
        data = await request.get_json()
        email = data.get("email")
        new_password = data.get("new_password")
        otp = data.get("otp")
        if not email or not new_password or not otp:
            return api_error(
                "Email, new password, and OTP are required",
                HTTPStatus.BAD_REQUEST
            )

        # Verify OTP before resetting password
        if not await self.verify_otp(
            email, otp, validate_only=True, context="forgot-password"
        ):
            return api_error("Invalid or expired OTP", HTTPStatus.UNAUTHORIZED)

        if await self.conn._reset_password(email, new_password):
            return api_response(
                "Password reset successfully",
                HTTPStatus.OK
            )
        else:
            return api_error(
                "Failed to reset password",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/auth/set-password", methods=["POST"])
    @jwt_required
    async def set_password(self):
        """Allow SSO users to set a password for dual authentication."""
        user_id = get_jwt_identity()
        data = await request.get_json()
        password = data.get("password")
        
        if not password:
            return api_error("Password is required", HTTPStatus.BAD_REQUEST)
        
        if len(password) < 8:
            return api_error(
                "Password must be at least 8 characters long",
                HTTPStatus.BAD_REQUEST
            )
        
        try:
            user_email = await self.conn.decrypt_credentials(user_id)
            user_email = user_email.decode() if isinstance(user_email, bytes) else user_email
            
            user = await self.conn._fetch_user_by_email(user_email)
            if not user:
                return api_error("User not found", HTTPStatus.NOT_FOUND)
            
            auth_provider = user.get("auth_provider", "password")
            
            if auth_provider not in ["google", "apple", "sso"]:
                return api_error(
                    "This endpoint is for SSO users only. Use /auth/reset-password to change your existing password.",
                    HTTPStatus.BAD_REQUEST
                )
            
            if user.get("hashed_password"):
                return api_error(
                    "Password already set. Use /auth/reset-password to change it.",
                    HTTPStatus.CONFLICT
                )
            
            updated_user = await self.conn.update_user({
                "id": user_id,
                "hashed_password": password
            })
            
            if updated_user:
                return api_response(
                    "Password set successfully. You can now login with either SSO or password.",
                    HTTPStatus.OK
                )
            else:
                return api_error(
                    "Failed to set password",
                    HTTPStatus.INTERNAL_SERVER_ERROR
                )
        except Exception as e:
            logger.error(f"Error setting password for user {user_id}: {e}")
            return api_error(
                "Failed to set password",
                HTTPStatus.INTERNAL_SERVER_ERROR
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
            return api_error("Already Exists.", HTTPStatus.CONFLICT)
        else:
            return api_response("Available.", HTTPStatus.OK)

    @route("/auth/verify", methods=["POST"])
    @rate_limit(**GlobalRateLimits.AUTH_LIMITS)
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
            return api_error("Invalid Request Body", HTTPStatus.BAD_REQUEST)

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
                return api_response(
                    "OTP verified successfully",
                    HTTPStatus.OK
                )

            if isinstance(result, dict):
                await self.conn._store_after_verify(result)
                access_token = self.generate_jwt_secret(result["id"])

                # Send welcome email on first registration (non-critical)
                if context == "register":
                    try:
                        await self.__notification_manager.send_welcome_notification(
                            user_id=result["id"],
                            first_name=(
                                result.get("organization_name")
                                or result.get("username")
                                or result.get("first_name")
                                or "there"
                            ),
                        )
                    except Exception as e:
                        logger.error("Welcome notification failed (non-blocking): %s", e)

                return api_response(
                    "OTP verified successfully.",
                    HTTPStatus.OK,
                    data={"access_token": access_token, "token_type": "bearer"}
                )
        else:
            return api_error("Invalid OTP", HTTPStatus.UNAUTHORIZED)

    @route("/auth/resend-otp", methods=["POST"])
    @rate_limit(**GlobalRateLimits.OTP_LIMITS)
    async def resend_otp(self):
        """Resend OTP for an email during registration or password reset.
        
        This endpoint is called when a user taps "Resend OTP" and only requires
        the email address. It does NOT trigger full registration.
        """
        data = await request.get_json()
        email = data.get("email")
        context = data.get("context", "register")  # "register" or "forgot-password"
        
        if not email:
            return api_error("Email is required", HTTPStatus.BAD_REQUEST)
        
        try:
            # Check if there's an existing Novu subscriber for this email
            existing_subscriber = await self.__notification_manager.get_subscriber_by_email(email)
            if existing_subscriber:
                user_id = existing_subscriber.subscriber_id
            else:
                # For resend, use a temporary ID if no subscriber exists yet
                user_id = str(ruuid.uuid4()).split("-")[-1]
            
            # Generate and send OTP without full registration
            if otp_result := await self.__generate_and_send_otp(
                user_id, email, None, get_client_ip(request), context=context
            ):
                response_data = {}
                if os.getenv("ENVIRONMENT") in ["dev", "test"]:
                    response_data["otp"] = otp_result
                
                return api_response(
                    "OTP resent successfully",
                    HTTPStatus.OK,
                    data=response_data
                )
            else:
                return api_error(
                    "OTP already sent. Please wait before requesting another.",
                    HTTPStatus.CONFLICT
                )
        except Exception as e:
            logger.error(f"Resend OTP error: {e}")
            return api_error(
                "Failed to resend OTP",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

    @route("/auth/register", methods=["POST"])
    @rate_limit(**GlobalRateLimits.AUTH_LIMITS)
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
            username_exists = await self.conn._check_exists(data.get("username", ""), "username")
            
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
                    
                    return api_error(message, HTTPStatus.CONFLICT)
            elif username_exists:
                # Username taken (but email is available)
                return api_error(
                    "Username already taken. Please choose a different username.",
                    HTTPStatus.CONFLICT
                )

            await self.__n_register_user(
                email=data.get("email"), user_data=data, user_id=data["id"]
            )
        except Exception as e:
            logger.error(f"Registration error: {e}")
            # Consider a more specific error response
            return api_error(
                "Registration failed due to an internal error.",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

        if otp_result := await self.__generate_and_send_otp(
            data["id"], data.get("email"), data, get_client_ip(request), context="register"
        ):
            # Return the OTP only in dev/test environments for easier testing
            response_data = {}
            if os.getenv("ENVIRONMENT") in ["dev", "test"]:
                response_data["otp"] = otp_result  # Include OTP for testing

            return api_response(
                "User registered, OTP sent.",
                HTTPStatus.CREATED,
                data=response_data
            )
        else:
            return api_error(
                "Existing OTP, please verify",
                HTTPStatus.CONFLICT
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
            return api_response(
                "KYC Data updated successfully.",
                HTTPStatus.OK
            )

    @route("/auth/kyc/session", methods=["POST"])
    @jwt_required
    async def create_kyc_session(self):
        """"""
        veriff_resp = await self.__veriff_client.create_session(user_id=get_jwt_identity())
        if not veriff_resp:
            return api_error(
                "Failed to create session in Veriff.",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )

        return api_response(
            "Veriff session created.",
            HTTPStatus.CREATED,
            data=veriff_resp
        )

    @route("/auth/login", methods=["POST"])
    @rate_limit(**GlobalRateLimits.AUTH_LIMITS)
    async def login_user(self):
        """Verify user credentials and generate an access token."""
        data = await request.get_json()
        result = await self.conn._login(data)
        
        # Handle SSO user without password set
        if isinstance(result, str):
            if result == "no_password_set":
                return api_error(
                    "This account uses SSO authentication. Please login with SSO first, then you can set a password in account settings for dual authentication.",
                    HTTPStatus.BAD_REQUEST
                )
        
        # Handle successful password login
        if result and isinstance(result, dict):
            access_token = self.generate_jwt_secret(result["id"])
            await self.__notification_manager.recent_login_notification(
                user_id=result["id"],
                ip_address=get_client_ip(request),
            )
            return api_response(
                "Login successful.",
                HTTPStatus.OK,
                data={"access_token": access_token, "token_type": "bearer"}
            )

        # Handle failed login (None result)
        return api_error(
            "Bad username or password",
            HTTPStatus.UNAUTHORIZED
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
            return api_error("Missing ID token", HTTPStatus.BAD_REQUEST)

        # try:
        # Verify the token
        idinfo = id_token.verify_oauth2_token(
            token_str, grequests.Request(), GOOGLE_CLIENT_ID
        )

        # Optional: check email is verified
        if not idinfo.get("email_verified"):
            return api_error("Email not verified", HTTPStatus.FORBIDDEN)

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
            return api_error(
                "Authentication failed, please try again",
                HTTPStatus.INTERNAL_SERVER_ERROR
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
        
        return api_response(
            message,
            status_code,
            data={"access_token": access_token, "token_type": "bearer"}
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
            return api_error("Missing identity token", HTTPStatus.BAD_REQUEST)
        
        if not APPLE_CLIENT_ID:
            return api_error(
                "Apple Sign In not configured",
                HTTPStatus.INTERNAL_SERVER_ERROR
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
                return api_error(
                    "Email not verified",
                    HTTPStatus.FORBIDDEN
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
                return api_error(
                    "Authentication failed, please try again",
                    HTTPStatus.INTERNAL_SERVER_ERROR
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
            
            return api_response(
                message,
                status_code,
                data={"access_token": access_token, "token_type": "bearer"}
            )
        
        except jwt.ExpiredSignatureError:
            logger.warning(f"Expired Apple token attempted from {get_client_ip()}")
            return api_error(
                "Apple token has expired, please sign in again",
                HTTPStatus.UNAUTHORIZED
            )
            
        except jwt.InvalidAudienceError:
            logger.error("Invalid audience in Apple token - client ID mismatch")
            return api_error(
                "Invalid Apple token configuration",
                HTTPStatus.UNAUTHORIZED
            )
            
        except jwt.InvalidIssuerError:
            logger.error("Invalid issuer in Apple token - not from Apple")
            return api_error(
                "Invalid Apple token source",
                HTTPStatus.UNAUTHORIZED
            )
            
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid Apple token from {get_client_ip()}: {e}")
            return api_error(
                "Invalid or malformed Apple token",
                HTTPStatus.UNAUTHORIZED
            )
            
        except Exception as e:
            logger.error(f"Unexpected error during Apple Sign In: {e}")
            return api_error(
                "Authentication service temporarily unavailable",
                HTTPStatus.INTERNAL_SERVER_ERROR
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
            # Guard against double-creation: if the user already has a Stripe
            # account ID stored, return a fresh onboarding link for it instead
            # of creating a second orphaned account in Stripe.
            existing_user = await self.conn._fetch_user(user_id, "stripe_account_id") if False else None
            # Fetch directly to check stripe_account_id
            import orjson as _j
            existing_check = await self.conn.pool.execute_query(
                "SELECT stripe_account_id FROM type::thing('users', $uid);",
                {"uid": user_id},
            )
            existing_account_id = (
                existing_check[0].get("stripe_account_id")
                if existing_check and existing_check[0]
                else None
            )
            if existing_account_id:
                logger.info(f"User {user_id} already has Stripe account {existing_account_id}, generating new link")
                account_link = await stripe.AccountLink.create_async(
                    account=existing_account_id,
                    refresh_url=url_for(".reauth_stripe", account_id=existing_account_id, _external=True).replace("http://", "https://"),
                    return_url=url_for(".stripe_return", account_id=existing_account_id, _external=True).replace("http://", "https://"),
                    type="account_onboarding",
                )
                return api_response(
                    "Stripe account link generated",
                    HTTPStatus.OK,
                    data={"url": account_link.url}
                )

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

            return api_response(
                "Stripe account link generated",
                HTTPStatus.OK,
                data={"url": account_link.url}
            )  # Frontend redirects to this URL
        except StripeError as e:
            return api_error(str(e), HTTPStatus.BAD_REQUEST)

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
            return api_error("User not found", HTTPStatus.NOT_FOUND)
        
        account = await stripe.Account.retrieve_async(account_id)

        app.logger.warning("%s | %s | %s", user["id"], account.id, account)
        app.logger.warning("Attempting to update user with stripe account id %s", account.id)

        await self.conn.update_user(
            {"id": user["id"], "stripe_account_kyc_status": True}
        )
        return api_response("Onboarding completed successfully", HTTPStatus.OK)

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
        return api_response(
            "Stripe account link generated",
            HTTPStatus.OK,
            data={"url": account_link.url}
        )

    async def __generate_and_send_otp(
        self,
        user_id: str,
        email: str,
        data: Optional[dict],
        ip_address: str,
        context: Literal["register", "forgot-password"],
    ) -> str | bool:
        """Generate and send OTP for authentication.

        Uses atomic SET NX so that two simultaneous requests for the same email
        can never both succeed — only the first SET wins, the second returns False
        without generating or sending anything.

        The OTP is deleted from Redis if notification delivery fails, so the user
        can immediately retry rather than being locked out for 10 minutes.
        """
        try:
            otp = secrets.token_hex(3)[:6].upper()
            key = f"{context}-otp:{email}"

            # Atomic SET NX — returns True only if the key did not already exist.
            # Eliminates the GET-then-SET TOCTOU window: two concurrent requests
            # both calling SET NX will have exactly one winner.
            was_set = await self.redis.set(key, otp, ex=600, nx=True)
            if not was_set:
                return False

            if data:
                await self.redis.set(
                    f"users:pending:{email}", json.dumps(data), ex=800
                )

            # Send notification AFTER the key is stored. If delivery fails, clean
            # up the key so the user can request a fresh OTP immediately rather
            # than hitting a "OTP already exists" block for 10 minutes.
            try:
                await self.__notification_manager.send_otp_notification(
                    user_id=user_id,
                    ip_address=ip_address,
                    otp=otp,
                )
            except Exception as notif_err:
                logger.error(f"OTP notification failed for {email}, rolling back key: {notif_err}")
                await self.redis.delete(key)
                if data:
                    await self.redis.delete(f"users:pending:{email}")
                raise

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

        return api_response("Webhook received", HTTPStatus.OK, data={"status": "received"})

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
                return api_error("User not found", HTTPStatus.NOT_FOUND)
            
            # Check if deletion is already scheduled
            if user_data[0].get("scheduled_deletion_at"):
                return api_response(
                    "Account deletion already scheduled",
                    HTTPStatus.CONFLICT,
                    data={"scheduled_deletion_at": user_data[0].get("scheduled_deletion_at")}
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
            
            return api_response(
                "Account deletion scheduled. You have 30 days to cancel.",
                HTTPStatus.OK,
                data={
                    "scheduled_deletion_at": deletion_date.isoformat(),
                    "message": "Your account is scheduled for deletion in 30 days",
                }
            )
        
        except Exception as e:
            logger.error(f"Account deletion scheduling error for user {user_id}: {e}")
            return api_error(
                "An error occurred while scheduling account deletion",
                HTTPStatus.INTERNAL_SERVER_ERROR
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
            
            if not user_data or not user_data[0]:
                return api_error("User not found", HTTPStatus.NOT_FOUND)

            # Check if deletion is scheduled
            if not user_data[0].get("scheduled_deletion_at"):
                return api_error("No scheduled deletion to cancel", HTTPStatus.BAD_REQUEST)
            
            # Cancel the scheduled deletion
            await self.conn.pool.execute_query(
                "UPDATE type::thing('users', $user_id) SET scheduled_deletion_at = NONE;",
                {"user_id": user_id}
            )
            
            logger.info(f"Cancelled scheduled deletion for user {user_id}")
            
            return api_response("Account deletion cancelled successfully", HTTPStatus.OK)
        
        except Exception as e:
            logger.error(f"Cancellation error for user {user_id}: {e}")
            return api_error(
                "An error occurred while cancelling deletion",
                HTTPStatus.INTERNAL_SERVER_ERROR
            )
    
    async def verify_otp(
        self,
        email: str,
        provided_otp: str,
        validate_only: Optional[bool],
        context: Literal["register", "forgot-password"],
        delete: bool = True,
    ) -> Optional[Dict] | bool:
        """Verify OTP for authentication.

        Uses GETDEL (atomic get-and-delete) when delete=True so two concurrent
        verification requests for the same OTP can never both succeed. The first
        request atomically claims and deletes the key; the second gets None and
        is rejected. Without this, two simultaneous requests could both GET the
        same valid OTP, both compare equal, and both issue tokens.

        For validate_only=True / delete=False (forgot-password first step) we
        still use a plain GET since the OTP must survive to be used in the
        subsequent reset-password call.
        """
        try:
            key = f"{context}-otp:{email}"

            if delete:
                # Atomic get-and-delete: exactly one concurrent caller gets the value.
                stored_otp = await self.redis.getdel(key)
            else:
                stored_otp = await self.redis.get(key)

            if not stored_otp or stored_otp != provided_otp:
                return False

            if validate_only:
                # forgot-password first step: OTP is valid, keep it for reset call.
                # (We already deleted it above only when delete=True, which the
                # caller sets False for this context — so the key is still alive.)
                return True

            # Full verification — fetch pending user data (may have expired).
            json_data = await self.redis.get(f"users:pending:{email}")
            if not json_data:
                return False
            json_data = json.loads(json_data)

            # Key already deleted above via GETDEL; clean up pending data.
            await self.redis.delete(f"users:pending:{email}")
            return json_data

        except Exception as e:
            logger.error(f"OTP verification error: {e}")
            raise