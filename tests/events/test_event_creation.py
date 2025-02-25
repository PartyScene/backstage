import pytest
from faker import Faker
from httpx import AsyncClient
from datetime import datetime, timedelta

fake = Faker()

@pytest.mark.asyncio
class TestEventCreation:
    async def test_create_valid_event(self, client, test_config, get_token):
        """Test creating a valid event."""
        event_data = {
            "title": fake.catch_phrase(),
            "description": fake.text(),
            "start_time": (datetime.now() + timedelta(days=1)).isoformat(),
            "coordinates": fake.latlng(),
            "location": fake.address(),
            "price": fake.numerify('##'),
        }

        
        response = await client.post("/events", json=event_data, headers={"Authorization": f"Bearer {get_token}"})
        assert response.status_code == 201
        created_event = response.json()
        
        assert created_event['title'] == event_data['title']
        assert 'id' in created_event

    @pytest.mark.parametrize("invalid_data", [
        {"title": ""},  # Empty title
        {"start_time": "invalid-date"},  # Invalid date format
        {"end_time": datetime.now().isoformat()}  # End time before start time
    ])
    async def test_create_invalid_event(self, client, invalid_data):
        """Test event creation with invalid data."""
        response = await client.post("/events", json=invalid_data)
        assert response.status_code == 400

    async def test_create_event_unauthorized(self, client):
        """Test event creation without authentication."""
        event_data = {
            "title": fake.catch_phrase(),
            "start_time": (datetime.now() + timedelta(days=1)).isoformat()
        }
        
        response = await client.post("/events", json=event_data)
        assert response.status_code == 401

@pytest.mark.performance
def test_event_creation_performance(benchmark, client):
    """Benchmark event creation performance."""
    event_data = {
        "title": fake.catch_phrase(),
        "start_time": (datetime.now() + timedelta(days=1)).isoformat(),
    }
    
    result = benchmark(client.post, "/events", json=event_data)
    assert result.status_code == 201