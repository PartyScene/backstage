import pytest
from faker import Faker
from httpx import AsyncClient
from datetime import datetime, timedelta

fake = Faker()

@pytest.mark.asyncio
class TestAuthentication:
    async def test_user_registration(self, async_client, mock_user):
        
        """Test user registration with valid data."""
        response = await async_client.post("/register", json=mock_user)
        print(vars(response))
        assert response.status_code == 201
        created_user = response.json()
        assert created_user['username'] == mock_user['username']
        assert 'id' in created_user
        assert 'password' not in created_user

    async def test_user_login(self, async_client, mock_user):
        """Test user login with valid credentials."""
        response = await async_client.post("/login", json=mock_user)
        assert response.status_code == 200
        login_response = response.json()
        
        assert 'access_token' in login_response
        assert 'token_type' in login_response
        assert login_response['token_type'] == 'bearer'

    @pytest.mark.parametrize("invalid_data", [
        {"email": "invalid-email", "password": "password123"},  # Invalid email format
        {"email": "", "password": "password123"},  # Empty email
        {"email": "valid@email.com", "password": ""}  # Empty password
    ])
    async def test_login_invalid_data(self, async_client, invalid_data):
        """Test login with invalid data."""
        response = await async_client.post("/login", json=invalid_data)
        assert response.status_code == 400

    # async def test_token_refresh(self, async_client, test_config):
    #     """Test refresh token endpoint."""
    #     # First login to get the refresh token
    #     login_data = {
    #         "email": test_config['test_user']['email'],
    #         "password": test_config['test_user']['password']
    #     }
    #     login_response = await async_client.post("/auth/login", json=login_data)
    #     refresh_token = login_response.json()['refresh_token']
        
    #     # Test token refresh
    #     response = await async_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    #     assert response.status_code == 200
    #     new_tokens = response.json()
        
    #     assert 'access_token' in new_tokens
    #     assert 'refresh_token' in new_tokens

    # async def test_password_reset_request(self, async_client, test_config):
    #     """Test password reset request functionality."""
    #     reset_data = {
    #         "email": test_config['test_user']['email']
    #     }
        
    #     response = await async_client.post("/auth/password-reset-request", json=reset_data)
    #     assert response.status_code == 200
        
    # @pytest.mark.performance
    # async def test_auth_performance(self, benchmark, async_client, mock_user):
    #     """Benchmark authentication performance."""
    #     result = await benchmark(async_client.post, "/auth/login", json=mock_user)
    #     assert result.status_code == 200