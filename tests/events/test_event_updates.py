import pytest
from faker import Faker

fake = Faker()

@pytest.mark.asyncio
class TestEventUpdates:
    async def test_update_event_details(self, async_client, created_event):
        """Test updating an existing event."""
        update_data = {
            "title": fake.catch_phrase(),
            "description": fake.text()
        }
        
        response = await async_client.patch(f"/events/{created_event['id']}", json=update_data)
        assert response.status_code == 200
        
        updated_event = response.json()
        assert updated_event['title'] == update_data['title']

    async def test_update_event_status(self, async_client, created_event):
        """Test changing event status."""
        status_update = {"status": "cancelled"}
        
        response = await async_client.patch(f"/events/{created_event['id']}/status", json=status_update)
        assert response.status_code == 200
        
        updated_event = response.json()
        assert updated_event['status'] == 'cancelled'