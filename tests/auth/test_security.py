import pytest
import base64
import json
from http import HTTPStatus
from test_base import TestAuthBase

@pytest.mark.security
@pytest.mark.asyncio(loop_scope="session")
class TestSecurity(TestAuthBase):
    """Security-related test cases for authentication endpoints."""

    async def test_jwt_tampering_detection(self, auth_client, mock_user):
        """Test that tampered JWT tokens are rejected."""
        # Login to get a valid token
        login_response = await self.login_user(auth_client, {
            "email": mock_user["email"],
            "password": mock_user["password"]
        })
        assert login_response.status_code == HTTPStatus.OK
        
        # Get the token and tamper with it
        token = (await login_response.get_json())["data"]["access_token"]
        parts = token.split('.')
        
        # Decode and tamper with the payload
        payload = json.loads(base64.b64decode(parts[1] + '===').decode('utf-8'))
        original_user_id = payload["sub"]
        payload["sub"] = "hacked_user_id"
        
        # Re-encode the tampered payload
        tampered_payload = base64.b64encode(
            json.dumps(payload).encode()
        ).decode().rstrip('=')
        tampered_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"
        
        # Try to access a protected endpoint with the tampered token
        response = await auth_client.get(
            "/user",
            headers={"Authorization": f"Bearer {tampered_token}"}
        )
        
        # Should reject the tampered token
        assert response.status_code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN)

    @pytest.mark.parametrize("attempts,expected_status", [
        (5, HTTPStatus.OK),  # Below rate limit
        (6, HTTPStatus.TOO_MANY_REQUESTS)  # Above rate limit
    ])
    async def test_login_rate_limiting(self, auth_client, mock_user, attempts, expected_status):
        """Test rate limiting on login endpoint."""
        credentials = {
            "email": mock_user["email"],
            "password": "wrong_password"  # Intentionally wrong to trigger failed login
        }
        
        last_status = None
        for _ in range(attempts):
            response = await auth_client.post("/auth/login", json=credentials)
            last_status = response.status_code
            
        assert last_status == expected_status

    async def test_token_expiration(self, auth_client, mock_user, mocker):
        """Test that expired tokens are rejected."""
        # Mock token expiration to 1 second
        mocker.patch('auth.src.views.base.ACCESS_EXPIRES', 1)
        
        # Login to get a token
        login_response = await self.login_user(auth_client, {
            "email": mock_user["email"],
            "password": mock_user["password"]
        })
        assert login_response.status_code == HTTPStatus.OK
        
        token = (await login_response.get_json())["data"]["access_token"]
        
        # Wait for token to expire
        import time
        time.sleep(2)
        
        # Try to access protected endpoint with expired token
        response = await auth_client.get(
            "/user",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Should reject the expired token
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert "Token has expired" in (await response.get_text())

    async def test_refresh_token_flow(self, auth_client, mock_user):
        """Test that refresh tokens can be used to get new access tokens."""
        # Login to get tokens
        login_response = await self.login_user(auth_client, {
            "email": mock_user["email"],
            "password": mock_user["password"]
        })
        assert login_response.status_code == HTTPStatus.OK
        
        refresh_token = (await login_response.get_json())["data"]["refresh_token"]
        
        # Use refresh token to get new access token
        refresh_response = await auth_client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {refresh_token}"}
        )
        
        assert refresh_response.status_code == HTTPStatus.OK
        assert "access_token" in (await refresh_response.get_json())["data"]
        
        # Verify the new access token works
        new_token = (await refresh_response.get_json())["data"]["access_token"]
        user_response = await auth_client.get(
            "/user",
            headers={"Authorization": f"Bearer {new_token}"}
        )
        
        assert user_response.status_code == HTTPStatus.OK

    async def test_invalid_refresh_token(self, auth_client):
        """Test that invalid refresh tokens are rejected."""
        response = await auth_client.post(
            "/auth/refresh",
            headers={"Authorization": "Bearer invalid.refresh.token"}
        )
        
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert "Not enough segments" in (await response.get_text()) or "Invalid token" in (await response.get_text())
