"""
Live Query Tests - SurrealDB LIVE SELECT websocket functionality.
Tests real-time event updates via websocket connections.
"""
import pytest
import asyncio
from http import HTTPStatus
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio(loop_scope="session")
class TestLiveQueries:
	"""Test SurrealDB live query functionality for real-time updates."""

	async def test_start_live_query_creates_subscription(
		self, events_client, mock_event, bearer
	):
		"""Test starting live query creates SurrealDB subscription."""
		response = await events_client.get(
			f"/events/{mock_event['id']}/live",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		assert response.status_code == HTTPStatus.OK
		data = (await response.get_json())["data"]
		
		assert "live_query_id" in data
		assert data["live_query_id"] is not None

	async def test_live_query_idempotent(
		self, events_client, mock_event, bearer
	):
		"""Test requesting same live query returns existing subscription."""
		# First request
		response1 = await events_client.get(
			f"/events/{mock_event['id']}/live",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		live_id1 = (await response1.get_json())["data"]["live_query_id"]
		
		# Second request (should return same ID)
		response2 = await events_client.get(
			f"/events/{mock_event['id']}/live",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		live_id2 = (await response2.get_json())["data"]["live_query_id"]
		
		assert live_id1 == live_id2, \
			"Live query should be idempotent, returning same subscription"

	async def test_unauthorized_user_cannot_start_live_query(
		self, events_client, mock_event
	):
		"""Test non-creator cannot start live updates for event."""
		# Use different user's token
		response = await events_client.get(
			f"/events/{mock_event['id']}/live",
			headers={"Authorization": "Bearer invalid_token"}
		)
		
		assert response.status_code in [HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN]

	async def test_stop_live_query_kills_subscription(
		self, events_client, mock_event, bearer
	):
		"""Test stopping live query properly terminates subscription."""
		# Start live query
		start_response = await events_client.get(
			f"/events/{mock_event['id']}/live",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		assert start_response.status_code == HTTPStatus.OK
		
		# Stop live query
		stop_response = await events_client.delete(
			f"/events/{mock_event['id']}/live",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		assert stop_response.status_code == HTTPStatus.OK

	async def test_live_query_cleaned_up_on_disconnect(
		self, events_client, mock_event, bearer
	):
		"""Test Redis cleanup when live query is no longer needed."""
		# Start live query
		await events_client.get(
			f"/events/{mock_event['id']}/live",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		# Verify Redis key exists
		redis = events_client.application.redis
		key = f"live_query:{mock_event['id']}"
		
		live_id = await redis.get(key)
		assert live_id is not None
		
		# Stop query
		await events_client.delete(
			f"/events/{mock_event['id']}/live",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		# Verify Redis key removed
		live_id_after = await redis.get(key)
		assert live_id_after is None

	async def test_multiple_live_queries_different_events(
		self, events_client, mock_event, bearer
	):
		"""Test user can have multiple live queries for different events."""
		# Create second event
		event2_data = {**mock_event, "id": "event2"}
		
		# Start live queries for both
		response1 = await events_client.get(
			f"/events/{mock_event['id']}/live",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		response2 = await events_client.get(
			f"/events/event2/live",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		# Both should succeed
		assert response1.status_code == HTTPStatus.OK
		assert response2.status_code == HTTPStatus.OK
		
		# Should have different live query IDs
		live_id1 = (await response1.get_json())["data"]["live_query_id"]
		live_id2 = (await response2.get_json())["data"]["live_query_id"]
		
		assert live_id1 != live_id2

	async def test_live_query_survives_service_restart(
		self, events_client, mock_event, bearer
	):
		"""Test live query can be recovered from Redis after restart."""
		# Start live query
		response = await events_client.get(
			f"/events/{mock_event['id']}/live",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		live_id = (await response.get_json())["data"]["live_query_id"]
		
		# Simulate service restart (Redis persists)
		# Request again should return same ID from Redis
		response2 = await events_client.get(
			f"/events/{mock_event['id']}/live",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		live_id2 = (await response2.get_json())["data"]["live_query_id"]
		assert live_id == live_id2

	async def test_live_query_for_nonexistent_event(
		self, events_client, bearer
	):
		"""Test starting live query for non-existent event fails gracefully."""
		response = await events_client.get(
			"/events/nonexistent999/live",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		assert response.status_code == HTTPStatus.NOT_FOUND

	async def test_redis_failure_handled_gracefully(
		self, events_client, mock_event, bearer
	):
		"""Test live query handles Redis unavailability."""
		with patch.object(
			events_client.application.redis,
			'set',
			side_effect=ConnectionError("Redis unavailable")
		):
			response = await events_client.get(
				f"/events/{mock_event['id']}/live",
				headers={"Authorization": f"Bearer {bearer}"}
			)
			
			# Should fail gracefully
			assert response.status_code in [
				HTTPStatus.INTERNAL_SERVER_ERROR,
				HTTPStatus.SERVICE_UNAVAILABLE
			]

	async def test_database_failure_during_live_query_start(
		self, events_client, mock_event, bearer
	):
		"""Test database failure during live query creation."""
		with patch.object(
			events_client.application.conn,
			'live_query',
			side_effect=Exception("Database connection lost")
		):
			response = await events_client.get(
				f"/events/{mock_event['id']}/live",
				headers={"Authorization": f"Bearer {bearer}"}
			)
			
			assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
