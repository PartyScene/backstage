import pytest
from test_base import TestAuthBase
import logging
from http import HTTPStatus

logger = logging.getLogger(__name__)


@pytest.mark.asyncio(loop_scope="session")
class TestAuthentication(TestAuthBase):

    async def test_user_registration(self, auth_client, mock_user):
        """Test user registration"""
        response = await self.register_user(auth_client, mock_user)
        response_json = await response.get_json()

        # Allow CONFLICT if user already exists from previous runs
        assert response.status_code in (HTTPStatus.CREATED, HTTPStatus.CONFLICT)

        if response.status_code == HTTPStatus.CREATED:
            assert response_json["status"] == HTTPStatus.CREATED.phrase
            assert "User registered, OTP sent." in response_json["message"]
            # OTP might be in 'data' field only in dev/test environments
            if "data" in response_json and "otp" in response_json["data"]:
                mock_user["otp"] = response_json["data"]["otp"]
            else:
                # Handle case where OTP is not returned (e.g., production)
                # Need a way to retrieve OTP for testing (e.g., mock Redis/email)
                pytest.skip("OTP not found in response, skipping OTP verification test")

        elif response.status_code == HTTPStatus.CONFLICT:
            assert response_json["status"] == HTTPStatus.CONFLICT.phrase
            assert "Credential Already Exists" in response_json["message"]
            if "Existing OTP" in response_json["message"]:
                if "data" in response_json and "otp" in response_json["data"]:
                    mock_user["otp"] = response_json["data"]["otp"]
                else:
                    # Handle case where OTP is not returned (e.g., production)
                    # Need a way to retrieve OTP for testing (e.g., mock Redis/email)
                    pytest.skip(
                        "OTP not found in response, skipping OTP verification test"
                    )
            # If conflict, we might not be able to proceed with OTP verification unless OTP exists
            # pytest.skip("User already exists, cannot reliably test OTP verification without existing OTP")

    async def test_other_user_registration(self, auth_client, other_mock_user):
        """Test Other User Reg"""
        response = await self.register_user(auth_client, other_mock_user)
        response_json = await response.get_json()

        # Allow CONFLICT if user already exists from previous runs
        assert response.status_code in (HTTPStatus.CREATED, HTTPStatus.CONFLICT)

        if response.status_code == HTTPStatus.CREATED:
            assert response_json["status"] == HTTPStatus.CREATED.phrase
            assert "User registered, OTP sent." in response_json["message"]
            # OTP might be in 'data' field only in dev/test environments
            if "data" in response_json and "otp" in response_json["data"]:
                other_mock_user["otp"] = response_json["data"]["otp"]
            else:
                # Handle case where OTP is not returned (e.g., production)
                # Need a way to retrieve OTP for testing (e.g., mock Redis/email)
                pytest.skip("OTP not found in response, skipping OTP verification test")

        elif response.status_code == HTTPStatus.CONFLICT:
            assert response_json["status"] == HTTPStatus.CONFLICT.phrase
            assert "Exist" in response_json["message"]
            if "Existing OTP" in response_json["message"]:
                # OTP might be in 'data' field only in dev/test environments
                if "data" in response_json and "otp" in response_json["data"]:
                    other_mock_user["otp"] = response_json["data"]["otp"]
                else:
                    # Handle case where OTP is not returned (e.g., production)
                    # Need a way to retrieve OTP for testing (e.g., mock Redis/email)
                    pytest.skip(
                        "OTP not found in response, skipping OTP verification test"
                    )
            # # If conflict, we might not be able to proceed with OTP verification unless OTP exists
            # pytest.skip("User already exists, cannot reliably test OTP verification without existing OTP")

    async def test_verify_otp(self, auth_client, mock_user):
        """Test OTP verification"""
        if "otp" not in mock_user:
            pytest.skip("OTP not available for verification test")

        response = await self.verify_otp(auth_client, mock_user, mock_user["otp"], "register")
        response_json = await response.get_json()

        assert response.status_code == HTTPStatus.OK
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "OTP verified successfully" in response_json["message"]
        assert "data" in response_json
        assert "access_token" in response_json["data"]
        assert "token_type" in response_json["data"]
        assert response_json["data"]["token_type"] == "bearer"

    async def test_other_verify_otp(self, auth_client, other_mock_user):
        """Test OTP verification"""
        if "otp" not in other_mock_user:
            pytest.skip("OTP not available for verification test")

        response = await self.verify_otp(auth_client, other_mock_user, other_mock_user["otp"], "register")
        response_json = await response.get_json()

        assert response.status_code == HTTPStatus.OK
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "OTP verified successfully" in response_json["message"]
        assert "data" in response_json
        assert "access_token" in response_json["data"]
        assert "token_type" in response_json["data"]
        assert response_json["data"]["token_type"] == "bearer"

    async def test_exists(self, auth_client, mock_user):
        """Test email and username existence"""
        # Assuming user exists from registration test
        response_email = await self.check_email_exists(auth_client, mock_user)
        response_email_json = await response_email.get_json()
        assert response_email.status_code == HTTPStatus.CONFLICT
        assert response_email_json["status"] == HTTPStatus.CONFLICT.phrase
        assert "Already Exists" in response_email_json["message"]
        logger.info(f"Email exists check response: {response_email_json}")

        response_username = await self.check_username_exists(auth_client, mock_user)
        response_username_json = await response_username.get_json()
        assert response_username.status_code == HTTPStatus.CONFLICT
        assert response_username_json["status"] == HTTPStatus.CONFLICT.phrase
        assert "Already Exists" in response_username_json["message"]
        logger.info(f"Username exists check response: {response_username_json}")

        # Test non-existent
        response_non_existent = await auth_client.get(
            "/auth/exists?type=email&param=nonexistent@example.com"
        )
        response_non_existent_json = await response_non_existent.get_json()
        assert response_non_existent.status_code == HTTPStatus.OK
        assert response_non_existent_json["status"] == HTTPStatus.OK.phrase
        assert "Available" in response_non_existent_json["message"]
    
    async def test_user_login(self, auth_client, mock_user):
        """Test user login"""
        login_credentials = {
            "email": mock_user["email"],
            "password": mock_user["password"],
        }
        response = await self.login_user(auth_client, login_credentials)
        response_json = await response.get_json()

        assert response.status_code == HTTPStatus.OK
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "Login successful" in response_json["message"]
        assert "data" in response_json
        assert "access_token" in response_json["data"]
        assert "token_type" in response_json["data"]
        assert response_json["data"]["token_type"] == "bearer"
    
    async def test_forgot_password(self, auth_client, mock_user):
        """Test forgot password and assign returned dev otp to user data"""
        response = await self.forget_password(auth_client, mock_user)
        response_json = await response.get_json()

        assert response.status_code == HTTPStatus.OK
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "OTP sent to your email for password reset." in response_json["message"]
        assert "data" in response_json
        assert "otp" in response_json["data"]
        mock_user["forgot_password_otp"] = response_json["data"]["otp"]
        
    async def test_verify_forgot_password_otp(self, auth_client, mock_user):
        """Test Forgot Pass OTP verification"""
        if "forgot_password_otp" not in mock_user:
            pytest.skip("Forgot password OTP not available for verification test")

        response = await self.verify_otp(auth_client, mock_user, mock_user['forgot_password_otp'], "forgot-password")
        response_json = await response.get_json()
        assert response.status_code == HTTPStatus.OK
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "OTP verified successfully" in response_json["message"]
        
    async def test_reset_password(self, auth_client, mock_user):
        """Test reset password by providing OTP and new password"""
        if "forgot_password_otp" not in mock_user:
            pytest.skip("Forgot password OTP not available for reset test")
        response = await self.reset_password(auth_client, mock_user)
        response_json = await response.get_json()

        assert response.status_code == HTTPStatus.OK
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "Password reset successfully" in response_json["message"]
    
    async def test_new_password_login(self, auth_client, mock_user):
        """Test user login with new password"""
        if "new_password" not in mock_user:
            pytest.skip("New password not available for login test")
        login_credentials = {
            "email": mock_user["email"],
            "password": mock_user["new_password"],
        }
        response = await self.login_user(auth_client, login_credentials)
        response_json = await response.get_json()

        assert response.status_code == HTTPStatus.OK
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "Login successful" in response_json["message"]
        assert "data" in response_json
        assert "access_token" in response_json["data"]
        assert "token_type" in response_json["data"]
        assert response_json["data"]["token_type"] == "bearer"
            
    async def test_lead_generation(self, auth_client):
        """Test lead generation"""
        lead_data = {
            "email": "leadtest@example.com",
            "usecase": "early access tester",
            "first_name": "Lead",
            "last_name": "Tester",
        }
        response = await self.lead_generation(auth_client, lead_data)
        response_json = await response.get_json()

        # Allow CONFLICT if lead already exists
        assert response.status_code in (
            HTTPStatus.CREATED,
            HTTPStatus.CONFLICT,
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )

        if response.status_code == HTTPStatus.CREATED:
            assert response_json["status"] == HTTPStatus.CREATED.phrase
            assert f"Created Lead {lead_data['email']}" in response_json["message"]
        elif response.status_code == HTTPStatus.CONFLICT:
            assert response_json["status"] == HTTPStatus.CONFLICT.phrase
            assert "Lead already exists" in response_json["message"]
        elif response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
            assert response_json["status"] == HTTPStatus.INTERNAL_SERVER_ERROR.phrase
            assert "Failed to create lead in Brevo" in response_json["message"]

    @pytest.mark.parametrize(
        "invalid_data",
        [
            {"email": "invalid@email.com", "password": "wrongpass"},
            {"email": "notanemail", "password": "testpass"},
            {"email": "", "password": ""},
        ],
    )
    async def test_login_invalid_data(self, auth_client, invalid_data):
        """Test login with invalid data"""
        response = await self.login_user(auth_client, invalid_data)
        response_json = await response.get_json()

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response_json["status"] == HTTPStatus.UNAUTHORIZED.phrase
        assert "Bad username or password" in response_json["message"]
