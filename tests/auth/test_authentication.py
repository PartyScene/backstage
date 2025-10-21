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

        response = await self.verify_otp(
            auth_client, mock_user, mock_user["otp"], "register"
        )
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

        response = await self.verify_otp(
            auth_client, other_mock_user, other_mock_user["otp"], "register"
        )
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

        response = await self.verify_otp(
            auth_client, mock_user, mock_user["forgot_password_otp"], "forgot-password"
        )
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
    
    async def test_account_deletion_without_auth(self, auth_client):
        """Test account deletion without authentication token"""
        response = await auth_client.delete("/auth/account")
        
        # Should return unauthorized without JWT token
        assert response.status_code == HTTPStatus.UNAUTHORIZED
    
    async def test_account_deletion_with_invalid_token(self, auth_client):
        """Test account deletion with invalid authentication token"""
        response = await auth_client.delete(
            "/auth/account",
            headers={"Authorization": "Bearer invalid_token_here"}
        )
        
        # Should return unauthorized with invalid token
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    
    async def test_account_deletion_scheduling(self, auth_client):
        """Test scheduling account deletion with 30-day grace period"""
        # Create a temporary user for deletion test
        temp_user = {
            "email": "scheduledel@test.com",
            "password": "ScheduleTest123!",
            "username": "scheduledel_user",
            "first_name": "Schedule",
            "last_name": "Delete",
        }
        
        # Register the user
        register_response = await self.register_user(auth_client, temp_user)
        register_json = await register_response.get_json()
        
        if register_response.status_code == HTTPStatus.CREATED:
            # Get OTP if available
            if "data" in register_json and "otp" in register_json["data"]:
                otp = register_json["data"]["otp"]
                
                # Verify OTP to get access token
                verify_response = await self.verify_otp(
                    auth_client, temp_user, otp, "register"
                )
                verify_json = await verify_response.get_json()
                
                if verify_response.status_code == HTTPStatus.OK:
                    access_token = verify_json["data"]["access_token"]
                    
                    # Schedule account deletion
                    delete_response = await self.delete_account(auth_client, access_token)
                    delete_json = await delete_response.get_json()
                    
                    # Verify deletion was scheduled
                    assert delete_response.status_code == HTTPStatus.OK
                    assert delete_json["status"] == HTTPStatus.OK.phrase
                    assert "30 days" in delete_json["message"]
                    assert "data" in delete_json
                    assert "scheduled_deletion_at" in delete_json["data"]
                    assert delete_json["data"]["days_remaining"] == 30
                    
                    # Verify user can still login during grace period
                    login_response = await self.login_user(
                        auth_client,
                        {"email": temp_user["email"], "password": temp_user["password"]}
                    )
                    assert login_response.status_code == HTTPStatus.OK
                    
                    # Cancel the scheduled deletion for cleanup
                    cancel_response = await self.cancel_account_deletion(auth_client, access_token)
                    cancel_json = await cancel_response.get_json()
                    assert cancel_response.status_code == HTTPStatus.OK
                    assert "cancelled" in cancel_json["message"].lower()
                else:
                    pytest.skip("Failed to verify OTP for deletion test")
            else:
                pytest.skip("OTP not available in dev/test environment")
        elif register_response.status_code == HTTPStatus.CONFLICT:
            # User already exists, try to login and schedule deletion
            login_response = await self.login_user(
                auth_client,
                {"email": temp_user["email"], "password": temp_user["password"]}
            )
            
            if login_response.status_code == HTTPStatus.OK:
                login_json = await login_response.get_json()
                access_token = login_json["data"]["access_token"]
                
                # Schedule account deletion
                delete_response = await self.delete_account(auth_client, access_token)
                delete_json = await delete_response.get_json()
                
                # Verify deletion was scheduled or already scheduled
                assert delete_response.status_code in (HTTPStatus.OK, HTTPStatus.CONFLICT)
                
                if delete_response.status_code == HTTPStatus.OK:
                    assert "30 days" in delete_json["message"]
                    
                    # Cancel for cleanup
                    cancel_response = await self.cancel_account_deletion(auth_client, access_token)
                    assert cancel_response.status_code == HTTPStatus.OK
            else:
                pytest.skip("Cannot login to existing user for deletion test")
        else:
            pytest.skip("Failed to create user for deletion test")
    
    async def test_cancel_account_deletion(self, auth_client):
        """Test canceling a scheduled account deletion"""
        # Create a temporary user
        temp_user = {
            "email": "canceltest@test.com",
            "password": "CancelTest123!",
            "username": "canceltest_user",
            "first_name": "Cancel",
            "last_name": "Test",
        }
        
        # Register and verify user
        register_response = await self.register_user(auth_client, temp_user)
        
        if register_response.status_code == HTTPStatus.CREATED:
            register_json = await register_response.get_json()
            if "data" in register_json and "otp" in register_json["data"]:
                otp = register_json["data"]["otp"]
                verify_response = await self.verify_otp(auth_client, temp_user, otp, "register")
                
                if verify_response.status_code == HTTPStatus.OK:
                    verify_json = await verify_response.get_json()
                    access_token = verify_json["data"]["access_token"]
                    
                    # Try to cancel when nothing is scheduled
                    cancel_response = await self.cancel_account_deletion(auth_client, access_token)
                    cancel_json = await cancel_response.get_json()
                    assert cancel_response.status_code == HTTPStatus.BAD_REQUEST
                    assert "No scheduled deletion" in cancel_json["message"]
                    
                    # Schedule deletion
                    delete_response = await self.delete_account(auth_client, access_token)
                    assert delete_response.status_code == HTTPStatus.OK
                    
                    # Cancel the deletion
                    cancel_response = await self.cancel_account_deletion(auth_client, access_token)
                    cancel_json = await cancel_response.get_json()
                    assert cancel_response.status_code == HTTPStatus.OK
                    assert "cancelled" in cancel_json["message"].lower()
                    
                    # Try to cancel again - should fail
                    cancel_response = await self.cancel_account_deletion(auth_client, access_token)
                    cancel_json = await cancel_response.get_json()
                    assert cancel_response.status_code == HTTPStatus.BAD_REQUEST
                else:
                    pytest.skip("Failed to verify OTP")
            else:
                pytest.skip("OTP not available")
        else:
            pytest.skip("User registration failed or already exists")
