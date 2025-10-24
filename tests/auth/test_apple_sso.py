import pytest
from test_base import TestAuthBase
import logging
from http import HTTPStatus
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# Use PyJWT directly like the shared utilities
import PyJWT as jwt

logger = logging.getLogger(__name__)


@pytest.mark.asyncio(loop_scope="session")
class TestAppleSSO(TestAuthBase):
    """Test Apple Sign In SSO authentication flow."""
    
    def generate_mock_apple_token(self, user_id: str, email: str) -> str:
        """
        Generate a mock Apple identity token for testing.
        
        Note: This is for testing only. In production, tokens come from Apple.
        """
        payload = {
            "iss": "https://appleid.apple.com",
            "aud": "com.scenesllc.partyscene",  # Your bundle ID
            "exp": int((datetime.now() + timedelta(hours=1)).timestamp()),
            "iat": int(datetime.now().timestamp()),
            "sub": user_id,  # Apple user ID
            "email": email,
            "email_verified": "true",
            "is_private_email": "false",
            "auth_time": int(datetime.now().timestamp()),
        }
        
        # Create unsigned token for testing
        # In production, Apple signs this with RS256
        return jwt.encode(payload, "", algorithm="HS256")
    
    async def test_apple_sso_missing_token(self, auth_client):
        """Test Apple SSO with missing identity token."""
        response = await auth_client.post(
            "/auth/apple",
            json={}
        )
        response_json = await response.get_json()
        
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "Missing identity token" in response_json["message"]
    
    @patch('shared.utils.apple_auth.AppleAuthClient.verify_identity_token')
    async def test_apple_sso_new_user_registration(
        self, 
        mock_verify,
        auth_client
    ):
        """Test Apple SSO registration for new user."""
        # Mock the token verification
        apple_user_id = "001234.abcdef123456.7890"
        email = "testapple@privaterelay.appleid.com"
        
        mock_verify.return_value = {
            "iss": "https://appleid.apple.com",
            "sub": apple_user_id,
            "email": email,
            "email_verified": "true",
        }
        
        # Prepare request data
        request_data = {
            "identity_token": self.generate_mock_apple_token(apple_user_id, email),
            "user": {
                "name": {
                    "firstName": "Apple",
                    "lastName": "User"
                },
                "email": email
            }
        }
        
        response = await auth_client.post("/auth/apple", json=request_data)
        response_json = await response.get_json()
        
        # Should create new user
        assert response.status_code in (HTTPStatus.CREATED, HTTPStatus.CONFLICT)
        
        if response.status_code == HTTPStatus.CREATED:
            assert "access_token" in response_json["data"]
            assert "token_type" in response_json["data"]
            assert response_json["data"]["token_type"] == "bearer"
            assert "User registered successfully" in response_json["message"]
    
    @patch('shared.utils.apple_auth.AppleAuthClient.verify_identity_token')
    async def test_apple_sso_existing_user_login(
        self,
        mock_verify,
        auth_client,
        mock_user
    ):
        """Test Apple SSO login for existing user."""
        # First, register a user with traditional method
        register_response = await self.register_user(auth_client, mock_user)
        
        if register_response.status_code == HTTPStatus.CREATED:
            register_json = await register_response.get_json()
            if "data" in register_json and "otp" in register_json["data"]:
                otp = register_json["data"]["otp"]
                await self.verify_otp(auth_client, mock_user, otp, "register")
        
        # Now try Apple SSO with same email
        apple_user_id = "001234.existing456.7890"
        
        mock_verify.return_value = {
            "iss": "https://appleid.apple.com",
            "sub": apple_user_id,
            "email": mock_user["email"],
            "email_verified": "true",
        }
        
        request_data = {
            "identity_token": self.generate_mock_apple_token(
                apple_user_id,
                mock_user["email"]
            )
        }
        
        response = await auth_client.post("/auth/apple", json=request_data)
        response_json = await response.get_json()
        
        # Should login existing user
        assert response.status_code == HTTPStatus.OK
        assert "access_token" in response_json["data"]
        assert "token_type" in response_json["data"]
        assert response_json["data"]["token_type"] == "bearer"
        assert "Login successful" in response_json["message"]
    
    @patch('shared.utils.apple_auth.AppleAuthClient.verify_identity_token')
    async def test_apple_sso_unverified_email(
        self,
        mock_verify,
        auth_client
    ):
        """Test Apple SSO with unverified email."""
        apple_user_id = "001234.unverified456.7890"
        email = "unverified@test.com"
        
        # Mock token with unverified email
        mock_verify.return_value = {
            "iss": "https://appleid.apple.com",
            "sub": apple_user_id,
            "email": email,
            "email_verified": "false",  # Not verified
        }
        
        request_data = {
            "identity_token": self.generate_mock_apple_token(apple_user_id, email)
        }
        
        response = await auth_client.post("/auth/apple", json=request_data)
        response_json = await response.get_json()
        
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "Email not verified" in response_json["message"]
    
    @patch('shared.utils.apple_auth.AppleAuthClient.verify_identity_token')
    async def test_apple_sso_invalid_token(
        self,
        mock_verify,
        auth_client
    ):
        """Test Apple SSO with invalid token."""
        # Mock token verification failure
        mock_verify.side_effect = jwt.InvalidTokenError("Invalid token")
        
        request_data = {
            "identity_token": "invalid.token.here"
        }
        
        response = await auth_client.post("/auth/apple", json=request_data)
        response_json = await response.get_json()
        
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert "Invalid Apple identity token" in response_json["message"]
    
    @patch('shared.utils.apple_auth.AppleAuthClient.verify_identity_token')
    async def test_apple_sso_private_relay_email(
        self,
        mock_verify,
        auth_client
    ):
        """Test Apple SSO with private relay email."""
        apple_user_id = "001234.privaterelay789.0123"
        private_email = "abc123def@privaterelay.appleid.com"
        
        mock_verify.return_value = {
            "iss": "https://appleid.apple.com",
            "sub": apple_user_id,
            "email": private_email,
            "email_verified": "true",
            "is_private_email": "true",
        }
        
        request_data = {
            "identity_token": self.generate_mock_apple_token(apple_user_id, private_email),
            "user": {
                "name": {
                    "firstName": "Private",
                    "lastName": "User"
                },
                "email": private_email
            }
        }
        
        response = await auth_client.post("/auth/apple", json=request_data)
        response_json = await response.get_json()
        
        # Should handle private relay emails
        assert response.status_code in (HTTPStatus.CREATED, HTTPStatus.CONFLICT, HTTPStatus.OK)
        
        if response.status_code in (HTTPStatus.CREATED, HTTPStatus.OK):
            assert "access_token" in response_json["data"]
            assert response_json["data"]["token_type"] == "bearer"
