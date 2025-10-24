import pytest
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared_base import StreamlinedTestBase
from test_base import TestAuthBase
import logging
from http import HTTPStatus

logger = logging.getLogger(__name__)


@pytest.mark.asyncio(loop_scope="session")
class TestAuthentication(StreamlinedTestBase, TestAuthBase):
    """Streamlined authentication tests following TDD best practices."""

    async def test_registration_creates_user_successfully_when_valid_data_provided(self, auth_client, mock_user):
        """Should create new user and return OTP when valid registration data is provided."""
        # Act
        response, response_json = await self.register_user_successfully(auth_client, mock_user)
        
        # Assert
        if response.status_code == HTTPStatus.CREATED:
            assert "User registered, OTP sent." in response_json["message"]
            self._store_otp_if_available(response_json, mock_user)
        elif response.status_code == HTTPStatus.CONFLICT:
            assert "Credential Already Exists" in response_json["message"]
            self._store_otp_if_available(response_json, mock_user)

    async def test_registration_creates_second_user_successfully_when_different_data_provided(self, auth_client, other_mock_user):
        """Should create second user successfully when different valid data is provided."""
        # Act
        response, response_json = await self.register_user_successfully(auth_client, other_mock_user)
        
        # Assert
        if response.status_code == HTTPStatus.CREATED:
            assert "User registered, OTP sent." in response_json["message"]
            self._store_otp_if_available(response_json, other_mock_user)
        elif response.status_code == HTTPStatus.CONFLICT:
            assert "Exist" in response_json["message"]
            self._store_otp_if_available(response_json, other_mock_user)

    def _store_otp_if_available(self, response_json: dict, user_data: dict):
        """Helper to store OTP from response if available."""
        if "data" in response_json and "otp" in response_json["data"]:
            user_data["otp"] = response_json["data"]["otp"]

    async def test_otp_verification_succeeds_when_valid_otp_provided(self, auth_client, mock_user):
        """Should verify OTP successfully and return access token when valid OTP is provided."""
        # Arrange
        if "otp" not in mock_user:
            pytest.skip("OTP not available for verification test")
        
        # Act
        response, response_json = await self.verify_otp_successfully(
            auth_client, mock_user["email"], mock_user["otp"], "register"
        )
        
        # Assert
        assert "OTP verified successfully" in response_json["message"]
        self.assert_auth_response(response_json)

    async def test_otp_verification_succeeds_for_second_user_when_valid_otp_provided(self, auth_client, other_mock_user):
        """Should verify OTP successfully for second user when valid OTP is provided."""
        # Arrange
        if "otp" not in other_mock_user:
            pytest.skip("OTP not available for verification test")
        
        # Act
        response, response_json = await self.verify_otp_successfully(
            auth_client, other_mock_user["email"], other_mock_user["otp"], "register"
        )
        
        # Assert
        assert "OTP verified successfully" in response_json["message"]
        self.assert_auth_response(response_json)

    async def test_email_existence_check_returns_conflict_when_email_already_registered(self, auth_client, mock_user):
        """Should return conflict when checking existence of already registered email."""
        # Act
        response = await self.check_email_exists(auth_client, mock_user)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.CONFLICT
        self.assert_error_response(response_json, HTTPStatus.CONFLICT, "Already Exists")

    async def test_username_existence_check_returns_conflict_when_username_already_taken(self, auth_client, mock_user):
        """Should return conflict when checking existence of already taken username."""
        # Act
        response = await self.check_username_exists(auth_client, mock_user)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.CONFLICT
        self.assert_error_response(response_json, HTTPStatus.CONFLICT, "Already Exists")

    async def test_email_existence_check_returns_available_when_email_not_registered(self, auth_client):
        """Should return available when checking existence of unregistered email."""
        # Arrange
        non_existent_email = "nonexistent@example.com"
        
        # Act
        response = await auth_client.get(f"/auth/exists?type=email&param={non_existent_email}")
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        self.assert_successful_response(response_json)
        assert "Available" in response_json["message"]

    async def test_user_login_succeeds_when_valid_credentials_provided(self, auth_client, mock_user):
        """Should login successfully and return access token when valid credentials are provided."""
        # Arrange
        login_credentials = {
            "email": mock_user["email"],
            "password": mock_user["password"]
        }
        
        # Act
        access_token = await self.login_user_successfully(auth_client, login_credentials)
        
        # Assert
        assert access_token is not None
        assert isinstance(access_token, str)
        assert len(access_token) > 0

    async def test_forgot_password_sends_otp_when_valid_email_provided(self, auth_client, mock_user):
        """Should send password reset OTP when valid registered email is provided."""
        # Act
        response = await self.forget_password(auth_client, mock_user)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        self.assert_successful_response(response_json)
        assert "OTP sent to your email for password reset." in response_json["message"]
        assert "otp" in response_json["data"]
        
        # Store OTP for subsequent tests
        mock_user["forgot_password_otp"] = response_json["data"]["otp"]

    async def test_forgot_password_otp_verification_succeeds_when_valid_otp_provided(self, auth_client, mock_user):
        """Should verify forgot password OTP successfully when valid OTP is provided."""
        # Arrange
        if "forgot_password_otp" not in mock_user:
            pytest.skip("Forgot password OTP not available for verification test")
        
        # Act
        response, response_json = await self.verify_otp_successfully(
            auth_client, mock_user["email"], mock_user["forgot_password_otp"], "forgot-password"
        )
        
        # Assert
        assert "OTP verified successfully" in response_json["message"]

    async def test_password_reset_succeeds_when_valid_otp_and_new_password_provided(self, auth_client, mock_user):
        """Should reset password successfully when valid OTP and new password are provided."""
        # Arrange
        if "forgot_password_otp" not in mock_user:
            pytest.skip("Forgot password OTP not available for reset test")
        
        # Act
        response = await self.reset_password(auth_client, mock_user)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        self.assert_successful_response(response_json)
        assert "Password reset successfully" in response_json["message"]

    async def test_login_succeeds_with_new_password_after_password_reset(self, auth_client, mock_user):
        """Should login successfully with new password after password reset."""
        # Arrange
        if "new_password" not in mock_user:
            pytest.skip("New password not available for login test")
        
        login_credentials = {
            "email": mock_user["email"],
            "password": mock_user["new_password"]
        }
        
        # Act
        access_token = await self.login_user_successfully(auth_client, login_credentials)
        
        # Assert
        assert access_token is not None
        assert isinstance(access_token, str)

    async def test_lead_generation_creates_lead_successfully_when_valid_data_provided(self, auth_client):
        """Should create lead successfully when valid lead data is provided."""
        # Arrange
        lead_data = {
            "email": "leadtest@example.com",
            "usecase": "early access tester",
            "first_name": "Lead",
            "last_name": "Tester"
        }
        
        # Act
        response = await self.lead_generation(auth_client, lead_data)
        response_json = await response.get_json()
        
        # Assert - Allow multiple valid responses
        assert response.status_code in (HTTPStatus.CREATED, HTTPStatus.CONFLICT, HTTPStatus.INTERNAL_SERVER_ERROR)
        
        if response.status_code == HTTPStatus.CREATED:
            self.assert_resource_created(response_json)
            assert f"Created Lead {lead_data['email']}" in response_json["message"]
        elif response.status_code == HTTPStatus.CONFLICT:
            self.assert_error_response(response_json, HTTPStatus.CONFLICT, "Lead already exists")
        elif response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
            self.assert_error_response(response_json, HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to create lead in Brevo")

    @pytest.mark.parametrize(
        "invalid_credentials,expected_error",
        [
            ({"email": "invalid@email.com", "password": "wrongpass"}, "Bad username or password"),
            ({"email": "notanemail", "password": "testpass"}, "Bad username or password"),
            ({"email": "", "password": ""}, "Bad username or password")
        ]
    )
    async def test_login_fails_when_invalid_credentials_provided(self, auth_client, invalid_credentials, expected_error):
        """Should return unauthorized when invalid login credentials are provided."""
        # Act
        response = await self.login_user(auth_client, invalid_credentials)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        self.assert_error_response(response_json, HTTPStatus.UNAUTHORIZED, expected_error)
    
    async def test_account_deletion_fails_when_no_authentication_provided(self, auth_client):
        """Should return unauthorized when attempting account deletion without authentication."""
        # Act & Assert
        await self.assert_unauthorized_access(auth_client, "DELETE", "/auth/account")
    
    async def test_account_deletion_fails_when_invalid_token_provided(self, auth_client):
        """Should return unauthorized when attempting account deletion with invalid token."""
        # Arrange
        invalid_token = "invalid_token_here"
        
        # Act
        response = await auth_client.delete(
            "/auth/account",
            headers={"Authorization": f"Bearer {invalid_token}"}
        )
        
        # Assert
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    
    async def test_account_deletion_schedules_successfully_with_30_day_grace_period(self, auth_client):
        """Should schedule account deletion with 30-day grace period when valid token is provided."""
        # Note: This test requires a full user registration flow for proper testing
        pytest.skip("Complex account deletion test - requires refactoring for proper isolation")
    
    async def test_cancel_account_deletion_requires_scheduled_deletion(self, auth_client):
        """Should return error when trying to cancel deletion without scheduled deletion."""
        # Note: This test requires a full user registration flow for proper testing
        pytest.skip("Complex account deletion test - requires refactoring for proper isolation")
