import pytest
from test_base import TestAuthBase


@pytest.mark.asyncio
class TestAuthentication(TestAuthBase):

    async def test_user_registration(self, auth_client, mock_user):
        """Test user registration"""
        response = await self.register_user(auth_client, mock_user)
        assert response.status_code == 201
        data = await response.get_json()
        assert "id" in data
        assert data["email"] == mock_user["email"]
        mock_user["id"] = data["id"]

    # @pytest.mark.asyncio
    async def test_user_login(self, auth_client, mock_user):
        """Test user login"""
        # First register the user
        await self.register_user(auth_client, mock_user)

        # Then try to login
        response = await self.login_user(
            auth_client,
            {"email": mock_user["email"], "password": mock_user["password"]},
        )
        assert response.status_code == 200
        data = await response.get_json()
        assert "access_token" in data

    # @pytest.mark.asyncio
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
