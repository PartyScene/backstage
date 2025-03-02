import pytest
from datetime import datetime, timedelta
from faker import Faker
from test_events_base import TestEventsBase

faker = Faker()


@pytest.mark.asyncio
class TestEventQueries(TestEventsBase):
    async def test_list_events(self, event_client, bearer):
        """Test retrieving a list of events."""
        response = await self.get_events(event_client, bearer)
        assert response.status_code == 200

        events = await response.get_json()
        assert isinstance(events, list)

    async def test_get_event(self, event_client, mock_event, bearer):
        """Test retrieving a list of events."""
        response = await self.get_event(event_client, mock_event["id"], bearer)
        assert "id" in mock_event

    # async def test_filter_events_by_date(self, client):
    #     """Test filtering events by date range."""
    #     start_date = datetime.now().isoformat()
    #     end_date = (datetime.now() + timedelta(days=30)).isoformat()

    #     response = await client.get(f"/events/location?start_date={start_date}&end_date={end_date}")
    #     assert response.status_code == 200

    #     filtered_events = await response.get_json()
    #     for event in filtered_events:
    #         event_start = datetime.fromisoformat(event['start_time'])
    #         assert start_date <= event_start.isoformat() <= end_date

    async def test_filter_events_by_location(self, event_client, bearer):
        """Test filtering events by distance from N meters."""
        response = await self.get_events_distance(event_client, faker.latlng(), bearer)

        assert response.status_code == 200

        filtered_events = await response.get_json()
        assert isinstance(filtered_events, list)
