import pytest
import urllib
from faker import Faker
from test_events_base import TestEventsBase
from datetime import datetime, timedelta
from quart.datastructures import FileStorage

fake = Faker()


@pytest.mark.asyncio(loop_scope="session")
class TestEventCreation(TestEventsBase):
    async def test_create_valid_event(self, event_client, mock_event, bearer):
        """Test creating a valid event."""

        files = {
            "file": FileStorage(
                self.generate_random_image(),
                filename="pytests/" + fake.file_name(category="image"),
                content_type="image/jpeg",
            )
        }

        response = await self.create_event(event_client, mock_event, files, bearer)
        created_event = await response.get_json()
        assert "id" in created_event
        assert response.status_code == 201


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
        files = {
            "file": FileStorage(
                self.generate_random_image(),
                filename="pytests/" + fake.file_name(category="image"),
                content_type="image/jpeg",
            )
        }
        response = await self.create_event(event_client, invalid_data, files, bearer)

        assert response.status_code == 400

# @pytest.mark.performance
# def test_event_creation_performance(benchmark, event_client):
#     """Benchmark event creation performance."""
#     event_data = {
#         "title": fake.catch_phrase(),
#         "start_time": (datetime.now() + timedelta(days=1)).isoformat(),
#     }

#     result = benchmark(event_client.post, "/events", json=event_data)
#     assert result.status_code == 201
