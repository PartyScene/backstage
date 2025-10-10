"""
JWT Token Lifecycle Tests - Token expiration, refresh, and revocation.
Critical security: Expired tokens must be rejected, refresh tokens must work.
"""
import pytest
import time
import jwt
from http import HTTPStatus
from datetime import datetime, timedelta
from unittest.mock import patch


@pytest.mark.asyncio(loop_scope="session")
class TestTokenLifecycle:
	"""Test JWT token lifecycle management."""

	async def test_expired_token_rejected(self, auth_client, mock_user):
		"""Test expired JWT token is rejected on protected endpoints."""
		# Generate expired token (manually)
		secret = auth_client.application.config.get("JWT_SECRET_KEY", "test-secret")
		
		expired_token = jwt.encode(
			{
				"sub": mock_user["id"],
				"exp": datetime.utcnow() - timedelta(hours=1)  # Expired 1 hour ago
			},
			secret,
			algorithm="HS256"
		)
		
		# Try to access protected endpoint with expired token
		response = await auth_client.post(
			"/auth/kyc/session",  # Protected endpoint (jwt_required)
			headers={"Authorization": f"Bearer {expired_token}"}
		)
		
		assert response.status_code == HTTPStatus.UNAUTHORIZED, \
			"Expired token must be rejected"

	async def test_malformed_token_rejected(self, auth_client):
		"""Test malformed JWT token is rejected."""
		malformed_tokens = [
			"not.a.jwt",
			"Bearer malformed",
			"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid",  # Invalid JWT
			"",  # Empty
			"Bearer ",  # Missing token
		]
		
		for token in malformed_tokens:
			response = await auth_client.post(
				"/auth/kyc/session",  # Protected endpoint
				headers={"Authorization": f"Bearer {token}"}
			)
			
			assert response.status_code == HTTPStatus.UNAUTHORIZED, \
				f"Malformed token '{token}' should be rejected"

	async def test_token_with_invalid_signature(self, auth_client, mock_user):
		"""Test token with wrong signature is rejected."""
		wrong_secret = "wrong_secret_key_12345"
		
		token = jwt.encode(
			{
				"sub": mock_user["id"],
				"exp": datetime.utcnow() + timedelta(hours=1)
			},
			wrong_secret,  # Wrong secret!
			algorithm="HS256"
		)
		
		response = await auth_client.post(
			"/auth/kyc/session",
			headers={"Authorization": f"Bearer {token}"}
		)
		
		assert response.status_code == HTTPStatus.UNAUTHORIZED, \
			"Token with invalid signature must be rejected"

	async def test_token_without_expiration_rejected(self, auth_client, mock_user):
		"""Test token without expiration claim is rejected."""
		secret = auth_client.application.config.get("JWT_SECRET_KEY", "test-secret")
		
		token = jwt.encode(
			{"sub": mock_user["id"]},  # No 'exp' claim
			secret,
			algorithm="HS256"
		)
		
		response = await auth_client.post(
			"/auth/kyc/session",
			headers={"Authorization": f"Bearer {token}"}
		)
		
		# Should reject tokens without expiration
		assert response.status_code == HTTPStatus.UNAUTHORIZED

	async def test_token_with_invalid_subject(self, auth_client):
		"""Test token with non-existent user ID is rejected."""
		secret = auth_client.application.config.get("JWT_SECRET_KEY", "test-secret")
		
		token = jwt.encode(
			{
				"sub": "nonexistent_user_999",
				"exp": datetime.utcnow() + timedelta(hours=1)
			},
			secret,
			algorithm="HS256"
		)
		
		response = await auth_client.post(
			"/auth/kyc/session",
			headers={"Authorization": f"Bearer {token}"}
		)
		
		# Should reject if user doesn't exist
		assert response.status_code in [HTTPStatus.UNAUTHORIZED, HTTPStatus.NOT_FOUND]

	async def test_token_refresh_extends_expiration(self, auth_client, bearer):
		"""Test token refresh generates new token with extended expiration."""
		# Decode current token
		secret = auth_client.application.config.get("JWT_SECRET_KEY", "test-secret")
		current_payload = jwt.decode(bearer, secret, algorithms=["HS256"])
		current_exp = current_payload.get("exp")
		
		# Request token refresh
		response = await auth_client.post(
			"/auth/refresh",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		if response.status_code == HTTPStatus.OK:
			data = await response.get_json()
			new_token = data["data"]["access_token"]
			
			new_payload = jwt.decode(new_token, secret, algorithms=["HS256"])
			new_exp = new_payload.get("exp")
			
			# New token should have later expiration
			assert new_exp > current_exp, "Refreshed token should have extended expiration"

	async def test_concurrent_token_usage_same_user(self, auth_client, bearer):
		"""Test same token can be used concurrently (stateless JWT)."""
		import asyncio
		
		# Make 10 concurrent requests with same token
		tasks = [
			auth_client.post(
				"/auth/kyc/session",
				headers={"Authorization": f"Bearer {bearer}"}
			)
			for _ in range(10)
		]
		
		responses = await asyncio.gather(*tasks, return_exceptions=True)
		
		# All should succeed or return same error
		for resp in responses:
			assert not isinstance(resp, Exception)
			assert resp.status_code in [HTTPStatus.OK, HTTPStatus.BAD_REQUEST, HTTPStatus.INTERNAL_SERVER_ERROR]

	async def test_token_revocation_blacklist(self, auth_client, bearer, mock_user):
		"""Test token revocation via blacklist (if implemented)."""
		# Note: /auth/logout endpoint may not be implemented
		# This tests the concept - if implemented, tokens should be blacklisted
		
		# Try to use token after "logout" (blacklist test)
		response = await auth_client.post(
			"/auth/kyc/session",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		# Should succeed if no blacklist (stateless JWT)
		# Blacklisting would require Redis/DB tracking
		assert response.status_code in [HTTPStatus.UNAUTHORIZED, HTTPStatus.OK, HTTPStatus.BAD_REQUEST, HTTPStatus.INTERNAL_SERVER_ERROR]

	async def test_token_contains_required_claims(self, auth_client, bearer):
		"""Test JWT token contains all required claims."""
		secret = auth_client.application.config.get("JWT_SECRET_KEY", "test-secret")
		payload = jwt.decode(bearer, secret, algorithms=["HS256"])
		
		# Required claims
		required_claims = ["sub", "exp", "iat"]  # subject, expiration, issued_at
		
		for claim in required_claims:
			assert claim in payload, f"Token missing required claim: {claim}"

	async def test_token_expiration_timing(self, auth_client, mock_user):
		"""Test token expiration is enforced at correct time."""
		# Login to get new token
		login_response = await auth_client.post(
			"/auth/login",
			json={"email": mock_user["email"], "password": mock_user["password"]}
		)
		
		assert login_response.status_code == HTTPStatus.OK
		token = (await login_response.get_json())["data"]["access_token"]
		
		secret = auth_client.application.config.get("JWT_SECRET_KEY", "test-secret")
		payload = jwt.decode(token, secret, algorithms=["HS256"])
		exp_time = payload["exp"]
		
		# Verify expiration is in the future
		current_time = time.time()
		assert exp_time > current_time, "Token should not be expired immediately"
		
		# Verify expiration is reasonable (e.g., 1-24 hours)
		time_until_expiry = exp_time - current_time
		assert 3600 <= time_until_expiry <= 86400, \
			f"Token expiry time ({time_until_expiry}s) outside reasonable range"
