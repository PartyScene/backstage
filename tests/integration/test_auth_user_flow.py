"""
Integration tests for auth -> user service flow.
Tests cross-service communication and data consistency.
"""
import pytest
import httpx
import os
from typing import Dict


@pytest.mark.integration
@pytest.mark.asyncio
class TestAuthUserIntegration:
	"""Test authentication and user service integration."""

	@pytest.fixture
	def base_urls(self) -> Dict[str, str]:
		"""Get service URLs from environment or use defaults."""
		return {
			"auth": os.getenv("AUTH_URL", "http://microservices.auth:5510"),
			"users": os.getenv("USERS_URL", "http://microservices.users:5514"),
		}

	async def test_register_and_fetch_user(self, base_urls):
		"""Test user registration creates accessible user profile."""
		async with httpx.AsyncClient(timeout=30.0) as client:
			# Register user
			registration_data = {
				"email": "integration_test@example.com",
				"password": "TestPass123!",
				"confirm_password": "TestPass123!",
				"first_name": "Integration",
				"last_name": "Test",
				"username": f"inttest_{os.urandom(4).hex()}",
			}
			
			auth_response = await client.post(
				f"{base_urls['auth']}/auth/register",
				json=registration_data
			)
			
			assert auth_response.status_code in [201, 409]
			
			if auth_response.status_code == 201:
				data = auth_response.json()
				assert "data" in data
				
				# Verify OTP and get token
				if "otp" in data["data"]:
					verify_response = await client.post(
						f"{base_urls['auth']}/auth/verify-otp",
						json={
							"email": registration_data["email"],
							"otp": data["data"]["otp"],
							"context": "register"
						}
					)
					
					assert verify_response.status_code == 200
					verify_data = verify_response.json()
					token = verify_data["data"]["access_token"]
					
					# Fetch user profile from users service
					user_response = await client.get(
						f"{base_urls['users']}/user",
						headers={"Authorization": f"Bearer {token}"}
					)
					
					assert user_response.status_code == 200
					user_data = user_response.json()
					assert user_data["data"]["email"] == registration_data["email"]

	async def test_login_and_access_protected_endpoint(self, base_urls):
		"""Test login flow provides valid token for protected endpoints."""
		async with httpx.AsyncClient(timeout=30.0) as client:
			# Login
			login_response = await client.post(
				f"{base_urls['auth']}/auth/login",
				json={
					"email": "doubra.ak@zohomail.com",
					"password": "testingTs"
				}
			)
			
			if login_response.status_code != 200:
				pytest.skip("Test user not available")
			
			data = login_response.json()
			token = data["data"]["access_token"]
			
			# Access protected user endpoint
			user_response = await client.get(
				f"{base_urls['users']}/user",
				headers={"Authorization": f"Bearer {token}"}
			)
			
			assert user_response.status_code == 200
			assert "data" in user_response.json()

	async def test_invalid_token_rejected(self, base_urls):
		"""Test invalid tokens are rejected by services."""
		async with httpx.AsyncClient(timeout=30.0) as client:
			response = await client.get(
				f"{base_urls['users']}/user",
				headers={"Authorization": "Bearer invalid_token_12345"}
			)
			
			assert response.status_code == 401
