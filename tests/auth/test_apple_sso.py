import pytest
from test_base import TestAuthBase
import logging
from http import HTTPStatus
from unittest.mock import patch
from datetime import datetime, timedelta
import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidAudienceError, InvalidIssuerError, InvalidTokenError

logger = logging.getLogger(__name__)


@pytest.mark.asyncio(loop_scope="session")
class TestAppleSSO(TestAuthBase):
    """Test Apple Sign In SSO authentication flow."""

    @pytest.fixture
    def apple_user_data(self):
        """Standard Apple user test data."""
        return {
            "user_id": "001234.abcdef123456.7890",
            "email": "testapple@privaterelay.appleid.com",
            "first_name": "Apple",
            "last_name": "User"
        }

    @pytest.fixture
    def private_relay_user_data(self):
        """Private relay Apple user test data."""
        return {
            "user_id": "001234.privaterelay789.0123",
            "email": "abc123def@privaterelay.appleid.com",
            "first_name": "Private",
            "last_name": "User"
        }

    def _create_apple_token_payload(self, user_id: str, email: str, email_verified: bool = True) -> dict:
        """Create Apple token payload for testing."""
        return {
            "iss": "https://appleid.apple.com",
            "aud": "com.scenesllc.partyscene",
            "exp": int((datetime.now() + timedelta(hours=1)).timestamp()),
            "iat": int(datetime.now().timestamp()),
            "sub": user_id,
            "email": email,
            "email_verified": "true" if email_verified else "false",
            "is_private_email": "false",
            "auth_time": int(datetime.now().timestamp()),
        }

    def _generate_mock_apple_token(self, user_id: str, email: str) -> str:
        """Generate mock Apple identity token."""
        payload = self._create_apple_token_payload(user_id, email)
        return jwt.encode(payload, "", algorithm="HS256")

    def _create_apple_sso_request(self, user_id: str, email: str, include_user_data: bool = True) -> dict:
        """Create Apple SSO request payload."""
        request = {"identity_token": self._generate_mock_apple_token(user_id, email)}
        
        if include_user_data:
            request["user"] = {
                "name": {"firstName": "Apple", "lastName": "User"},
                "email": email
            }
        
        return request

    def _mock_token_verification(self, mock_verify, user_id: str, email: str, email_verified: bool = True):
        """Setup token verification mock."""
        mock_verify.return_value = self._create_apple_token_payload(user_id, email, email_verified)

    def _assert_successful_auth_response(self, response_json: dict):
        """Assert successful authentication response structure."""
        assert "data" in response_json
        assert "access_token" in response_json["data"]
        assert "token_type" in response_json["data"]
        assert response_json["data"]["token_type"] == "bearer"
    
    async def test_apple_sso_rejects_request_without_identity_token(self, auth_client):
        """Should reject request when identity_token is missing."""
        # Arrange
        request_data = {}
        
        # Act
        response = await auth_client.post("/auth/apple", json=request_data)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "Missing identity token" in response_json["message"]
    
    @patch('shared.utils.apple_auth.AppleAuthClient.verify_identity_token')
    async def test_apple_sso_creates_new_user_successfully(self, mock_verify, auth_client, apple_user_data):
        """Should create new user when valid Apple SSO token is provided."""
        # Arrange
        self._mock_token_verification(mock_verify, apple_user_data["user_id"], apple_user_data["email"])
        request_data = self._create_apple_sso_request(apple_user_data["user_id"], apple_user_data["email"])
        
        # Act
        response = await auth_client.post("/auth/apple", json=request_data)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.CREATED
        # API returns access_token at root of data if successful, or in 'data' key
        # Adjust assertion to match API response format in auth/src/views/base.py
        self._assert_successful_auth_response(response_json)
        assert "User registered successfully" in response_json["message"]
    
    @patch('shared.utils.apple_auth.AppleAuthClient.verify_identity_token')
    async def test_apple_sso_logs_in_existing_user_successfully(self, mock_verify, auth_client, mock_user):
        """Should log in existing user when Apple SSO token matches registered email."""
        # Arrange - Create existing user
        register_response = await self.register_user(auth_client, mock_user)
        if register_response.status_code == HTTPStatus.CREATED:
            register_json = await register_response.get_json()
            if "data" in register_json and "otp" in register_json["data"]:
                otp = register_json["data"]["otp"]
                await self.verify_otp(auth_client, mock_user, otp, "register")
        
        apple_user_id = "001234.existing456.7890"
        self._mock_token_verification(mock_verify, apple_user_id, mock_user["email"])
        request_data = self._create_apple_sso_request(apple_user_id, mock_user["email"], include_user_data=False)
        
        # Act
        response = await auth_client.post("/auth/apple", json=request_data)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        self._assert_successful_auth_response(response_json)
        assert "Login successful" in response_json["message"]
    
    @patch('shared.utils.apple_auth.AppleAuthClient.verify_identity_token')
    async def test_apple_sso_rejects_unverified_email(self, mock_verify, auth_client):
        """Should reject Apple SSO request when email is not verified."""
        # Arrange
        apple_user_id = "001234.unverified456.7890"
        email = "unverified@test.com"
        self._mock_token_verification(mock_verify, apple_user_id, email, email_verified=False)
        request_data = self._create_apple_sso_request(apple_user_id, email, include_user_data=False)
        
        # Act
        response = await auth_client.post("/auth/apple", json=request_data)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "Email not verified" in response_json["message"]
    
    @patch('shared.utils.apple_auth.AppleAuthClient.verify_identity_token')
    async def test_apple_sso_rejects_invalid_token(self, mock_verify, auth_client):
        """Should reject request when Apple token verification fails."""
        # Arrange
        mock_verify.side_effect = jwt.InvalidTokenError("Invalid token")
        request_data = {"identity_token": "invalid.token.here"}
        
        # Act
        response = await auth_client.post("/auth/apple", json=request_data)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert "Invalid Apple identity token" in response_json["message"]
    
    @patch('shared.utils.apple_auth.AppleAuthClient.verify_identity_token')
    async def test_apple_sso_handles_private_relay_email_successfully(self, mock_verify, auth_client, private_relay_user_data):
        """Should successfully create user with Apple private relay email."""
        # Arrange
        user_data = private_relay_user_data
        payload = self._create_apple_token_payload(user_data["user_id"], user_data["email"])
        payload["is_private_email"] = "true"
        mock_verify.return_value = payload
        
        request_data = self._create_apple_sso_request(user_data["user_id"], user_data["email"])
        request_data["user"]["name"]["firstName"] = user_data["first_name"]
        request_data["user"]["name"]["lastName"] = user_data["last_name"]
        
        # Act
        response = await auth_client.post("/auth/apple", json=request_data)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.CREATED
        self._assert_successful_auth_response(response_json)
    
    @patch('shared.utils.apple_auth.AppleAuthClient.verify_identity_token')
    async def test_apple_sso_user_password_login_returns_proper_error_message(self, mock_verify, auth_client, apple_user_data):
        """Should return specific Apple SSO error when Apple user tries to log in with password."""
        # Arrange - First create Apple SSO user
        self._mock_token_verification(mock_verify, apple_user_data["user_id"], apple_user_data["email"])
        request_data = self._create_apple_sso_request(apple_user_data["user_id"], apple_user_data["email"])
        
        # Create Apple SSO user
        sso_response = await auth_client.post("/auth/apple", json=request_data)
        assert sso_response.status_code == HTTPStatus.CREATED
        
        # Act - Try to login with password credentials
        login_data = {
            "email": apple_user_data["email"],
            "password": "somepassword123"
        }
        response = await auth_client.post("/auth/login", json=login_data)
        response_json = await response.get_json()
        
        # Assert - Should get specific Apple SSO error message
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "This account was created with Apple Sign-In. Please use Apple Sign-In to log in." in response_json["message"]
        assert response_json["error_code"] == "MUST_USE_APPLE_SSO"
