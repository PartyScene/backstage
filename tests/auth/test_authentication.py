import pytest
from test_base import TestAuthBase
import logging


@pytest.mark.asyncio(loop_scope="session")
class TestAuthentication(TestAuthBase):

    async def test_user_registration(self, auth_client, mock_user):
        """Test user registration"""
        response = await self.register_user(auth_client, mock_user)
        assert response.status_code in (201, 409)
        data = await response.get_data(as_text=True)
        mock_user["otp"] = data

    async def test_verify_otp(self, auth_client, mock_user):
        """Test OTP verification"""
        response = await self.verify_otp(auth_client, mock_user)
        assert response.status_code == 200
        data = await response.get_json()
        assert "access_token" in data

    async def test_exists(self, auth_client, mock_user):
        """Test email and username existence"""
        response = await self.check_email_exists(auth_client, mock_user)
        assert response.status_code == 409
        data = await response.get_data(as_text=True)
        logging.info(data)

        response = await self.check_username_exists(auth_client, mock_user)
        assert response.status_code == 409
        data = await response.get_data(as_text=True)
        logging.info(data)

    async def test_lead_generation(self, auth_client):
        """Test lead generation"""
        response = await self.lead_generation(
            auth_client,
            {
                "email": "dylee@tutamail.com",
                "usecase": "early access tester",
                "first_name": "John",
                "last_name": "Doe",
            },
        )
        assert response.status_code == 201

    async def test_user_login(self, auth_client, mock_user):
        """Test user login"""
        response = await self.login_user(
            auth_client,
            {"email": mock_user["email"], "password": mock_user["password"]},
        )
        assert response.status_code == 200
        data = await response.get_json()
        assert "access_token" in data

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
        assert response.status_code == 401
