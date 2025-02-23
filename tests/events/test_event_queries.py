import pytest
from datetime import datetime, timedelta

@pytest.mark.asyncio
class TestEventQueries:
    async def test_list_events(self, async_client):
        """Test retrieving a list of events."""
        response = await async_client.get("/events")
        assert response.status_code == 200
        
        events = response.json()
        assert isinstance(events, list)

    async def test_filter_events_by_date(self, async_client):
        """Test filtering events by date range."""
        start_date = datetime.now().isoformat()
        end_date = (datetime.now() + timedelta(days=30)).isoformat()
        
        response = await async_client.get(f"/events?start_date={start_date}&end_date={end_date}")
        assert response.status_code == 200
        
        filtered_events = response.json()
        for event in filtered_events:
            event_start = datetime.fromisoformat(event['start_time'])
            assert start_date <= event_start.isoformat() <= end_date