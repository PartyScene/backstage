from dataclasses import dataclass
from datetime import timedelta, datetime
from pprint import pprint
from http import HTTPStatus
from quart import make_response, render_template, current_app as app, request, jsonify
from quart_schema import validate_request, validate_response, document_querystring

from ..connectors import AuthDB

import sys
sys.path.append('/app/shared')

from classful import route, QuartClassful

from quart_jwt_extended import create_access_token
from shared.notifications import NotificationManager
from redis.asyncio import Redis

import secrets
import logging

logger = logging.getLogger(__name__)

class BaseView(QuartClassful):

    def __init__(self):
        self.db: AuthDB = app.db
        self.redis: Redis = app.redis
        self.__notification_manager = NotificationManager()
        
    @route("/register", methods=["POST"])
    async def register_user(self):
        """
        Register a user account into the SurrealDB.
        """
        data = await request.get_json()
        created_acct = await self.db._create_user(data)
        try:
            await self.__n_register_user(created_acct)
            await self.__n_generate_otp(created_acct['id'], created_acct['email'])
        except Exception as e:
            logger.error(f"Registration error: {e}")
            raise
        return jsonify(created_acct), HTTPStatus.CREATED

    @route("/login", methods=["POST"])
    async def _login_user(self):
        """
        Verify user credentials
        """
        data = await request.get_json()
        if result := await self.db._login(data):
            access_token = create_access_token(identity=result['id'], expires_delta=timedelta(days=1))
            await self.__notification_manager.recent_login_notification(
                user_id=result['id'],
                payload=
                {
                    "ip_address": request.remote_addr,
                    "timeStamp": datetime.now().isoformat(),
                })
            return jsonify(access_token=access_token, token_type = "bearer"), HTTPStatus.OK
        return jsonify({"msg": "Bad username or password"}), HTTPStatus.UNAUTHORIZED
    
    
    async def __n_register_user(self, user_data: dict):
        """
        Register a new user and create Novu subscriber
        """
        try:
            
            # Create Novu subscriber
            return await self.__notification_manager.create_subscriber(
                user_id=user_data['id'],
                email=user_data['email'],
                first_name=user_data.get('first_name'),
                last_name=user_data.get('last_name')
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
            await self.redis.set(
                f"otp:{user_id}", 
                otp, 
                ex=600  # 10 minutes expiration
            )
            
            # Send OTP via Novu
            await self.__notification_manager.send_otp_notification(
                user_id=user_id, 
                otp=otp
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
