import pytest
from faker import Faker
from httpx import AsyncClient
from datetime import datetime, timedelta
from test_livestream_base import TestLiveStreamBase

fake = Faker()


@pytest.mark.asyncio(loop_scope="session")
class TestLiveStreamManagement(TestLiveStreamBase):
    async def test_create_stream(self, livestream_client, mock_event, bearer):
        """Test creating a new livestream session."""
        response = await self.create_live_stream(
            livestream_client, mock_event["id"], bearer
        )
        assert response.status_code == 201
        created_stream = await response.get_json()

        # assert created_stream['title'] == mock_event['title']
        assert "ingest_url" in created_stream
        assert "playback_url" in created_stream

    async def test_get_stream_info(self, livestream_client, mock_event, bearer):
        """Test retrieving stream information."""
        # First create a stream
        # create_response = await self.create_live_stream(livestream_client, mock_stream)
        # stream_id = await create_response.get_json()['id']

        response = await self.get_live_stream(
            livestream_client, mock_event["id"], bearer
        )
        assert response.status_code == 200
        stream_info = await response.get_json()

        assert "playback_url" in stream_info

        # assert 'viewer_count' in stream_info
        # assert 'status' in stream_info

    async def test_delete_stream_info(self, livestream_client, mock_event, bearer):
        """Test deleting stream information."""
        # First create a stream
        # create_response = await self.create_live_stream(livestream_client, mock_stream)
        # stream_id = await create_response.get_json()['id']

        response = await self.get_live_stream(
            livestream_client, mock_event["id"], bearer
        )
        assert response.status_code == 200

        response = await self.delete_live_stream(
            livestream_client, mock_event["id"], bearer
        )
        assert response.status_code == 204
        stream_info = await response.get_json()

        assert "channel_name" in stream_info

    # async def test_update_stream_settings(self, livestream_client):
    #     """Test updating stream settings."""
    #     # First create a stream
    #     stream_data = {
    #         "title": fake.catch_phrase(),
    #         "category": "gaming"
    #     }
    #     create_response = await livestream_client.post("/livestream/create", json=stream_data)
    #     stream_id = create_response.json()['id']

    #     # Update settings
    #     update_data = {
    #         "title": fake.catch_phrase(),
    #         "description": fake.text(max_nb_chars=200),
    #         "category": "education",
    #         "tags": [fake.word() for _ in range(3)]
    #     }

    #     response = await livestream_client.put(f"/livestream/{stream_id}/settings", json=update_data)
    #     assert response.status_code == 200
    #     updated_stream = response.json()

    #     assert updated_stream['title'] == update_data['title']
    #     assert updated_stream['category'] == update_data['category']

    # async def test_stream_chat_operations(self, async_client):
    #     """Test stream chat functionality."""
    #     # First create a stream
    #     stream_data = {"title": fake.catch_phrase()}
    #     create_response = await async_client.post("/livestream/create", json=stream_data)
    #     stream_id = create_response.json()['id']

    #     # Send chat message
    #     chat_message = {
    #         "content": fake.sentence(),
    #         "type": "text"
    #     }
    #     response = await async_client.post(f"/livestream/{stream_id}/chat", json=chat_message)
    #     assert response.status_code == 201

    #     # Get chat history
    #     history_response = await async_client.get(f"/livestream/{stream_id}/chat/history")
    #     assert history_response.status_code == 200
    #     chat_history = history_response.json()

    #     assert isinstance(chat_history, list)
    #     assert len(chat_history) > 0

    # @pytest.mark.parametrize("invalid_data", [
    #     {"title": ""},  # Empty title
    #     {"category": "invalid-category"},  # Invalid category
    #     {"scheduled_start": "invalid-date"}  # Invalid date format
    # ])
    # async def test_create_invalid_stream(self, livestream_client, invalid_data, bearer):
    #     """Test stream creation with invalid data."""
    #     response = await self.create_live_stream(livestream_client, invalid_data, bearer)
    #     assert response.status_code == 400

    # @pytest.mark.performance
    # def test_stream_performance(self, benchmark, async_client):
    #     """Benchmark stream data retrieval performance."""
    #     # First create a stream
    #     stream_data = {"title": fake.catch_phrase()}
    #     create_response = async_client.post("/livestream/create", json=stream_data)
    #     stream_id = create_response.json()['id']

    #     result = benchmark(async_client.get, f"/livestream/{stream_id}")
    #     assert result.status_code == 200
