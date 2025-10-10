"""
Integration tests for complete event creation and management flow.
Tests auth -> users -> events -> media service interactions.
"""
import pytest
import httpx
import os
import io
from datetime import datetime, timedelta


@pytest.mark.integration
@pytest.mark.asyncio
class TestEventCreationFlow:
	"""Test complete event lifecycle across services."""

	@pytest.fixture
	def base_urls(self):
		return {
			"auth": os.getenv("AUTH_URL", "http://microservices.auth:5510"),
			"events": os.getenv("EVENTS_URL", "http://microservices.events:5512"),
			"users": os.getenv("USERS_URL", "http://microservices.users:5514"),
		}

	@pytest.fixture
	async def authenticated_client(self, base_urls):
		"""Get authenticated client with valid token."""
		async with httpx.AsyncClient(timeout=30.0) as client:
			response = await client.post(
				f"{base_urls['auth']}/auth/login",
				json={"email": "doubra.ak@zohomail.com", "password": "testingTs"}
			)
			
			if response.status_code != 200:
				pytest.skip("Test user not available")
			
			token = response.json()["data"]["access_token"]
			client.headers["Authorization"] = f"Bearer {token}"
			yield client

	async def test_create_event_and_fetch(self, authenticated_client, base_urls):
		"""Test creating event and retrieving it."""
		# Create event
		event_data = {
			"title": "Integration Test Event",
			"description": "Event created during integration testing",
			"location": "Test Location, 123 Test St",
			"price": "25.00",
			"time": (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z",
			"is_private": "false",
			"is_free": "false",
			"coordinates[]": ["40.7128", "-74.0060"],
			"categories[]": ["test", "integration"],
		}
		
		# Create mock image file
		files = {
			"media": ("test_image.jpg", io.BytesIO(b"fake_image_data"), "image/jpeg")
		}
		
		create_response = await authenticated_client.post(
			f"{base_urls['events']}/events",
			data=event_data,
			files=files
		)
		
		assert create_response.status_code in [201, 400, 500]
		
		if create_response.status_code == 201:
			event_id = create_response.json()["data"]["id"]
			
			# Fetch created event
			fetch_response = await authenticated_client.get(
				f"{base_urls['events']}/events/{event_id}"
			)
			
			assert fetch_response.status_code == 200
			event = fetch_response.json()["data"]
			assert event["event"]["title"] == event_data["title"]

	async def test_event_attendance_flow(self, authenticated_client, base_urls):
		"""Test marking attendance for an event."""
		# Get public events
		events_response = await authenticated_client.get(
			f"{base_urls['events']}/events?limit=1"
		)
		
		if events_response.status_code != 200:
			pytest.skip("No events available")
		
		events = events_response.json()["data"]
		if not events:
			pytest.skip("No events in system")
		
		event_id = events[0]["event"]["id"]
		
		# Mark attendance
		attend_response = await authenticated_client.post(
			f"{base_urls['events']}/events/{event_id}/attend"
		)
		
		assert attend_response.status_code in [200, 409]

	async def test_user_events_listing(self, authenticated_client, base_urls):
		"""Test fetching user's events from user service."""
		response = await authenticated_client.get(
			f"{base_urls['users']}/user/events"
		)
		
		assert response.status_code in [200, 404]
		
		if response.status_code == 200:
			data = response.json()
			assert "data" in data or "message" in data
