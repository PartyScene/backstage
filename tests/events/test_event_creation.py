import pytest
import urllib
from faker import Faker
from test_events_base import TestEventsBase
from datetime import datetime, timedelta

fake = Faker()


@pytest.mark.asyncio
class TestEventCreation(TestEventsBase):
    async def test_create_valid_event(self, event_client, mock_event, bearer):
        """Test creating a valid event."""

        # response = await event_client.post("/events", json=mock_event, headers={"Authorization": f"Bearer {bearer}"})
        response = await self.create_event(event_client, mock_event, bearer)
        assert response.status_code == 201
        created_event = await response.get_json()

        mock_event["id"] = created_event["id"]

        assert created_event["host"] == mock_event["host"]
        assert "id" in created_event

    @pytest.mark.parametrize(
        "invalid_data",
        [
            {"title": ""},  # Empty title
            {"start_time": "invalid-date"},  # Invalid date format
            {"end_time": datetime.now().isoformat()},  # End time before start time
        ],
    )
    async def test_create_invalid_event(self, event_client, invalid_data, bearer):
        """Test event creation with invalid data."""
        # response = await event_client.post("/events", json=invalid_data, headers={"Authorization": f"Bearer {bearer}"})
        response = await self.create_event(event_client, invalid_data, bearer)

        assert response.status_code == 400

    async def test_create_event_unauthorized(self, event_client, bearer):
        """Test event creation without authentication."""
        event_data = {
            "title": fake.catch_phrase(),
            "start_time": (datetime.now() + timedelta(days=1)).isoformat(),
        }

        response = await event_client.post("/events", json=event_data)
        assert response.status_code == 401


# @pytest.mark.performance
# def test_event_creation_performance(benchmark, event_client):
#     """Benchmark event creation performance."""
#     event_data = {
#         "title": fake.catch_phrase(),
#         "start_time": (datetime.now() + timedelta(days=1)).isoformat(),
#     }

#     result = benchmark(event_client.post, "/events", json=event_data)
#     assert result.status_code == 201
