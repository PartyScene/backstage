import pytest
from faker import Faker
from httpx import AsyncClient
from datetime import datetime
from test_users_base import TestUsersBase

fake = Faker()


@pytest.mark.asyncio(loop_scope="session")
class TestUserManagement(TestUsersBase):

    async def test_get_user_profile(self, users_client, mock_user, bearer):
        """Test retrieving a user profile."""
        user_id = mock_user["id"]
        response = await self.get_user(users_client, user_id, bearer)

        assert response.status_code == 200
        profile = await response.get_json()
        assert "email" in profile

    async def test_update_user_profile(self, users_client, mock_user, bearer):
        """Test updating user profile information."""
        update_data = {"username": fake.name(), "bio": fake.text(max_nb_chars=200)}

        response = await self.update_user(users_client, update_data, bearer)
        assert response.status_code == 200
        updated_profile = await response.get_json()

        assert updated_profile["username"] == update_data["username"]
        assert updated_profile["bio"] == update_data["bio"]

    async def test_create_connection(self, users_client, mock_user, bearer):
        """Test creating a connection."""
        target_id = mock_user["id"]
        response = await self.create_connection(users_client, target_id, bearer)
        assert response.status_code == 201
        created_response = await response.get_json()

        assert created_response[0]["status"] in ("accepted", "pending")

    async def test_fetch_connections(self, users_client, mock_user, bearer):
        """Test fetching all connections."""
        response = await self.fetch_connections(users_client, bearer)
        assert response.status_code == 200
        response = await response.get_json()

        assert isinstance(response, dict)
        assert "degree_1" in response

    async def test_delete_connection(self, users_client, mock_user, bearer):
        """Test deleting a connection."""
        # Create connection first
        response = await self.create_connection(users_client, mock_user["id"], bearer)
        assert response.status_code == 201
        created_response = await response.get_json()

        connection_id = created_response[0]["id"]
        response = await self.delete_connection(users_client, connection_id, bearer)
        assert response.status_code == 204

    async def test_update_connection(self, users_client, mock_user, bearer):
        """Test updating a connection."""
        # Create connection first
        response = await self.create_connection(users_client, mock_user["id"], bearer)
        assert response.status_code == 201
        created_response = await response.get_json()

        # Then update it
        connection_id = created_response[0]["id"]
        response = await self.update_connection(
            users_client, connection_id, "accepted", bearer
        )
        assert response.status_code == 200
        updated_response = await response.get_json()

        assert updated_response["status"] == "accepted"

    # @pytest.mark.parametrize("invalid_data", [
    #     {"display_name": ""},  # Empty display name
    #     {"bio": "x" * 1001},  # Bio too long
    #     {"interests": "not-a-list"}  # Invalid interests format
    # ])
    # async def test_invalid_profile_updates(self, users_client, invalid_data, mock_user, bearer):
    #     """Test profile updates with invalid data."""
    #     response = await self.update_user(users_client, invalid_data, bearer)
    #     assert response.status_code == 400

    # async def test_user_search(self, users_client):
    #     """Test user search functionality."""
    #     search_query = {
    #         "query": fake.word(),
    #         "limit": 10
    #     }

    #     response = await users_client.get("/users/search", params=search_query)
    #     assert response.status_code == 200
    #     results = response.json()

    #     assert isinstance(results, list)
    #     assert len(results) <= search_query['limit']

    # @pytest.mark.performance
    # def test_profile_retrieval_performance(self, benchmark, users_client, test_config):
    #     """Benchmark profile retrieval performance."""
    #     user_id = test_config['test_user']['id']

    #     result = benchmark(users_client.get, f"/users/{user_id}/profile")
    #     assert result.status_code == 200
