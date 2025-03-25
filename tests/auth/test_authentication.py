import pytest
from test_base import TestAuthBase


@pytest.mark.asyncio(loop_scope="session")
class TestAuthentication(TestAuthBase):

    async def test_service_health(self, auth_client):
        for _ in range(25):
            response = await self.health_check(auth_client)
            assert response.status_code == 200
        data = await response.get_json()
        assert data["status"] == "healthy"

    async def test_user_registration(self, auth_client, mock_user):
        """Test user registration"""
        response = await self.register_user(auth_client, mock_user)
        assert response.status_code in (201, 409)
        # data = await response.get_json()
        # assert "id" in data

    # @pytest.mark.asyncio(loop_scope="session")
    async def test_user_login(self, auth_client, mock_user):
        """Test user login"""

        # Then try to login
        response = await self.login_user(
            auth_client,
            {"email": mock_user["email"], "password": mock_user["password"]},
        )
        assert response.status_code == 200
        data = await response.get_json()
        assert "access_token" in data

    # @pytest.mark.asyncio(loop_scope="session")
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
