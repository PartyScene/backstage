import pytest
from faker import Faker
from httpx import AsyncClient
from datetime import datetime

fake = Faker()

@pytest.mark.asyncio
class TestUserManagement:
    async def test_create_user_profile(self, async_client, test_config):
        """Test creating a user profile with valid data."""
        profile_data = {
            "display_name": fake.name(),
            "bio": fake.text(max_nb_chars=200),
            "location": fake.city(),
            "avatar_url": fake.image_url(),
            "interests": [fake.word() for _ in range(3)]
        }
        
        response = await async_client.post("/users/profile", json=profile_data)
        assert response.status_code == 201
        created_profile = response.json()
        
        assert created_profile['display_name'] == profile_data['display_name']
        assert 'id' in created_profile

    async def test_get_user_profile(self, async_client, test_config):
        """Test retrieving a user profile."""
        user_id = test_config['test_user']['id']
        response = await async_client.get(f"/users/{user_id}/profile")
        
        assert response.status_code == 200
        profile = response.json()
        assert 'display_name' in profile
        assert 'bio' in profile

    async def test_update_user_profile(self, async_client, test_config):
        """Test updating user profile information."""
        update_data = {
            "display_name": fake.name(),
            "bio": fake.text(max_nb_chars=200)
        }
        
        response = await async_client.put("/users/profile", json=update_data)
        assert response.status_code == 200
        updated_profile = response.json()
        
        assert updated_profile['display_name'] == update_data['display_name']
        assert updated_profile['bio'] == update_data['bio']

    @pytest.mark.parametrize("invalid_data", [
        {"display_name": ""},  # Empty display name
        {"bio": "x" * 1001},  # Bio too long
        {"interests": "not-a-list"}  # Invalid interests format
    ])
    async def test_invalid_profile_updates(self, async_client, invalid_data):
        """Test profile updates with invalid data."""
        response = await async_client.put("/users/profile", json=invalid_data)
        assert response.status_code == 400

    async def test_user_search(self, async_client):
        """Test user search functionality."""
        search_query = {
            "query": fake.word(),
            "limit": 10
        }
        
        response = await async_client.get("/users/search", params=search_query)
        assert response.status_code == 200
        results = response.json()
        
        assert isinstance(results, list)
        assert len(results) <= search_query['limit']

    @pytest.mark.performance
    def test_profile_retrieval_performance(self, benchmark, async_client, test_config):
        """Benchmark profile retrieval performance."""
        user_id = test_config['test_user']['id']
        
        result = benchmark(async_client.get, f"/users/{user_id}/profile")
        assert result.status_code == 200