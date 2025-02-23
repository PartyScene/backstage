import pytest
from faker import Faker
from httpx import AsyncClient
from datetime import datetime, timedelta

fake = Faker()

@pytest.mark.asyncio
class TestEventCreation:
    async def test_create_valid_event(self, async_client, test_config):
        """Test creating a valid event."""
        event_data = {
            "title": fake.catch_phrase(),
            "description": fake.text(),
            "start_time": (datetime.now() + timedelta(days=1)).isoformat(),
            "end_time": (datetime.now() + timedelta(days=2)).isoformat(),
            "location": fake.address(),
            "organizer_id": test_config['test_user']['id']
        }
        
        response = await async_client.post("/events", json=event_data)
        assert response.status_code == 201
        created_event = response.json()
        
        assert created_event['title'] == event_data['title']
        assert 'id' in created_event

    @pytest.mark.parametrize("invalid_data", [
        {"title": ""},  # Empty title
        {"start_time": "invalid-date"},  # Invalid date format
        {"end_time": datetime.now().isoformat()}  # End time before start time
    ])
    async def test_create_invalid_event(self, async_client, invalid_data):
        """Test event creation with invalid data."""
        response = await async_client.post("/events", json=invalid_data)
        assert response.status_code == 400

    async def test_create_event_unauthorized(self, async_client):
        """Test event creation without authentication."""
        event_data = {
            "title": fake.catch_phrase(),
            "start_time": (datetime.now() + timedelta(days=1)).isoformat()
        }
        
        response = await async_client.post("/events", json=event_data)
        assert response.status_code == 401

@pytest.mark.performance
def test_event_creation_performance(benchmark, async_client, test_config):
    """Benchmark event creation performance."""
    event_data = {
        "title": fake.catch_phrase(),
        "start_time": (datetime.now() + timedelta(days=1)).isoformat(),
        "organizer_id": test_config['test_user']['id']
    }
    
    result = benchmark(async_client.post, "/events", json=event_data)
    assert result.status_code == 201