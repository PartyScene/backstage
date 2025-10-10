"""Integration test configuration and fixtures."""
import pytest
import httpx
import asyncio
import os


@pytest.fixture(scope="session")
def event_loop():
	"""Create event loop for async tests."""
	loop = asyncio.get_event_loop_policy().new_event_loop()
	yield loop
	loop.close()


@pytest.fixture(scope="session")
def service_urls():
	"""Provide service URLs for integration tests."""
	return {
		"auth": os.getenv("AUTH_URL", "http://microservices.auth:5510"),
		"users": os.getenv("USERS_URL", "http://microservices.users:5514"),
		"events": os.getenv("EVENTS_URL", "http://microservices.events:5512"),
		"posts": os.getenv("POSTS_URL", "http://microservices.posts:5513"),
		"media": os.getenv("MEDIA_URL", "http://microservices.media:5515"),
	}


@pytest.fixture(scope="session")
async def health_check(service_urls):
	"""Verify all services are healthy before running tests."""
	async with httpx.AsyncClient(timeout=10.0) as client:
		for service_name, url in service_urls.items():
			try:
				response = await client.get(f"{url}/health")
				if response.status_code != 200:
					pytest.fail(f"{service_name} service unhealthy: {response.status_code}")
			except Exception as e:
				pytest.fail(f"{service_name} service unreachable: {str(e)}")
	
	return True
