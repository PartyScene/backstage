import pytest
from faker import Faker
from test_events_base import TestEventsBase

fake = Faker()

@pytest.mark.asyncio
class TestEventUpdates(TestEventsBase):
    async def test_update_event_details(self, event_client, mock_event, bearer):
        """Test updating an existing event."""
        update_data = {
            "title": fake.catch_phrase(),
            "description": fake.text()
        }
        response = await self.update_event(event_client, mock_event['id'], update_data, bearer)
        assert response.status_code == 200
        
        updated_event = await response.get_json()
        assert updated_event['title'] == update_data['title']

    async def test_update_event_status(self, event_client, mock_event, bearer):
        """Test changing event status."""
        status_update = {"status": "cancelled"}
        
        response = await self.update_event_status(event_client, mock_event['id'], status_update, bearer)
        # response = await client.patch(f"/events/{data['id']}/status", json=status_update)
        assert response.status_code == 200
        
        updated_event = await response.get_json()
        assert updated_event['status'] == 'cancelled'