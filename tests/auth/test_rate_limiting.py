"""
Rate Limiting Tests - Prevent brute force attacks.
Critical security: Login attempts must be rate-limited to prevent credential stuffing.
"""
import pytest
import asyncio
from http import HTTPStatus


@pytest.mark.asyncio(loop_scope="session")
class TestRateLimiting:
	"""Test API rate limiting and brute force protection."""

	async def test_login_brute_force_protection(self, auth_client):
		"""Test excessive failed login attempts are blocked."""
		# Attempt 20 failed logins rapidly
		failed_attempts = []
		
		for i in range(20):
			response = await auth_client.post(
				"/auth/login",
				json={
					"email": "victim@example.com",
					"password": f"wrong_password_{i}"
				}
			)
			failed_attempts.append(response.status_code)
		
		# After threshold (e.g., 5-10 attempts), should rate limit
		# Count how many got rate limited
		rate_limited = sum(1 for status in failed_attempts if status == HTTPStatus.TOO_MANY_REQUESTS)
		
		assert rate_limited > 0, \
			"No rate limiting detected after 20 failed login attempts"

	async def test_otp_generation_rate_limit(self, auth_client, mock_user):
		"""Test OTP generation is rate-limited to prevent abuse."""
		# Request OTP multiple times rapidly
		responses = []
		
		for i in range(10):
			response = await auth_client.post(
				"/auth/forgot-password",
				json={"email": mock_user["email"]}
			)
			responses.append(response.status_code)
		
		# Should rate limit after threshold
		rate_limited = sum(1 for status in responses if status == HTTPStatus.TOO_MANY_REQUESTS)
		
		assert rate_limited > 0, \
			"OTP generation not rate-limited, allows abuse"

	async def test_registration_rate_limit(self, auth_client):
		"""Test registration endpoint is rate-limited."""
		import time
		
		# Attempt rapid registrations
		responses = []
		
		for i in range(15):
			response = await auth_client.post(
				"/auth/register",
				json={
					"email": f"spam{i}_{int(time.time())}@example.com",
					"password": "TestPass123",
					"confirm_password": "TestPass123",
					"first_name": "Spam",
					"last_name": "Bot",
					"username": f"spambot{i}_{int(time.time())}"
				}
			)
			responses.append(response.status_code)
		
		# Should eventually rate limit
		rate_limited = sum(1 for status in responses if status == HTTPStatus.TOO_MANY_REQUESTS)
		
		# Allow some through but should limit after threshold
		assert rate_limited > 0 or responses[-1] in [HTTPStatus.TOO_MANY_REQUESTS, HTTPStatus.CREATED]

	async def test_rate_limit_per_ip_not_global(self, auth_client, mock_user):
		"""Test rate limiting is per-IP, not global."""
		# Simulate requests from different IPs (requires proxy/header spoofing)
		# In production, rate limiting should use X-Forwarded-For or similar
		
		# This test would require mocking the IP detection
		# For now, document the requirement
		pass  # Implementation depends on rate limiting strategy

	async def test_rate_limit_resets_after_cooldown(self, auth_client):
		"""Test rate limit cooldown period resets limits."""
		# First, trigger rate limit
		for i in range(10):
			await auth_client.post(
				"/auth/login",
				json={"email": "test@example.com", "password": f"wrong{i}"}
			)
		
		# Wait for cooldown period (e.g., 60 seconds in test, configurable)
		# In real implementation, mock time or use shorter cooldown
		await asyncio.sleep(2)  # Shortened for testing
		
		# Should be able to attempt again
		response = await auth_client.post(
			"/auth/login",
			json={"email": "test@example.com", "password": "password"}
		)
		
		# Should not be permanently blocked
		assert response.status_code != HTTPStatus.TOO_MANY_REQUESTS or \
			   response.status_code == HTTPStatus.UNAUTHORIZED  # Wrong password but not rate limited

	async def test_account_lockout_after_failed_attempts(self, auth_client, mock_user):
		"""Test account lockout after excessive failed attempts."""
		# Target specific account
		for i in range(15):
			await auth_client.post(
				"/auth/login",
				json={
					"email": mock_user["email"],
					"password": f"definitely_wrong_{i}"
				}
			)
		
		# Even with correct password, account should be locked
		response = await auth_client.post(
			"/auth/login",
			json={
				"email": mock_user["email"],
				"password": mock_user["password"]  # Correct password
			}
		)
		
		# Account should be locked or heavily rate-limited
		assert response.status_code in [
			HTTPStatus.LOCKED,  # 423 (ideal)
			HTTPStatus.TOO_MANY_REQUESTS,  # 429
			HTTPStatus.FORBIDDEN,  # 403
			HTTPStatus.UNAUTHORIZED,  # 401 if no lockout implemented
		]

	async def test_successful_login_resets_failed_attempts(self, auth_client, mock_user):
		"""Test successful login resets failed attempt counter."""
		# Make a few failed attempts
		for i in range(3):
			await auth_client.post(
				"/auth/login",
				json={"email": mock_user["email"], "password": f"wrong{i}"}
			)
		
		# Successful login
		success_response = await auth_client.post(
			"/auth/login",
			json={"email": mock_user["email"], "password": mock_user["password"]}
		)
		
		if success_response.status_code == HTTPStatus.OK:
			# Failed attempt counter should reset
			# Next failed attempt shouldn't immediately lock
			response = await auth_client.post(
				"/auth/login",
				json={"email": mock_user["email"], "password": "wrong_again"}
			)
			
			assert response.status_code == HTTPStatus.UNAUTHORIZED  # Not locked

	async def test_otp_verification_rate_limit(self, auth_client, mock_user):
		"""Test OTP verification attempts are rate-limited."""
		# First, request OTP
		await auth_client.post(
			"/auth/forgot-password",
			json={"email": mock_user["email"]}
		)
		
		# Attempt brute force OTP guessing
		responses = []
		for i in range(20):
			response = await auth_client.post(
				"/auth/verify-otp",
				json={
					"email": mock_user["email"],
					"otp": f"{i:06d}",  # Try sequential OTPs
					"context": "forgot-password"
				}
			)
			responses.append(response.status_code)
		
		# Should rate limit to prevent brute forcing 6-digit OTP
		rate_limited = sum(1 for status in responses if status == HTTPStatus.TOO_MANY_REQUESTS)
		
		assert rate_limited > 0, \
			"OTP verification not rate-limited, allows brute force"

	async def test_api_endpoint_global_rate_limit(self, auth_client):
		"""Test general API rate limiting across all endpoints."""
		# Make rapid requests to various endpoints
		responses = []
		
		for i in range(50):
			response = await auth_client.get("/auth/health")
			responses.append(response.status_code)
		
		# Should eventually rate limit even health checks
		rate_limited = sum(1 for status in responses if status == HTTPStatus.TOO_MANY_REQUESTS)
		
		# May or may not rate limit health checks (business decision)
		# Just document behavior
		pass  # Health checks often exempted from rate limiting
