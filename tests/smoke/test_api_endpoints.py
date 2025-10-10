"""
Smoke tests for API endpoints.
Quick validation of critical paths in production/staging.
"""
import pytest
import httpx
import os


BASE_URL = os.getenv("BASE_URL", "http://localhost:5510")


@pytest.mark.smoke
@pytest.mark.asyncio
class TestSmokeAPI:
	"""Basic smoke tests for API health and critical endpoints."""

	async def test_auth_health(self):
		"""Test auth service is responding."""
		async with httpx.AsyncClient() as client:
			response = await client.get(f"{BASE_URL}/users/health")
			assert response.status_code == 200
			data = response.json()
			assert data["data"]["status"] in ["healthy", "degraded"]

	async def test_events_health(self):
		"""Test events service is responding."""
		async with httpx.AsyncClient() as client:
			response = await client.get(f"{BASE_URL}/events/health")
			assert response.status_code == 200

	async def test_public_events_endpoint(self):
		"""Test public events can be fetched without auth."""
		async with httpx.AsyncClient() as client:
			response = await client.get(f"{BASE_URL}/events")
			assert response.status_code in [200, 404]

	async def test_login_endpoint_exists(self):
		"""Test login endpoint is accessible."""
		async with httpx.AsyncClient() as client:
			response = await client.post(
				f"{BASE_URL}/auth/login",
				json={"email": "test@test.com", "password": "wrong"}
			)
			assert response.status_code in [400, 401, 422]

	async def test_protected_endpoint_requires_auth(self):
		"""Test protected endpoints reject unauthenticated requests."""
		async with httpx.AsyncClient() as client:
			response = await client.get(f"{BASE_URL}/user")
			assert response.status_code == 401
