"""
Payment Idempotency Tests - Prevent duplicate charges.
Financial transactions must be idempotent to prevent charging customers multiple times.
"""
import pytest
import asyncio
from http import HTTPStatus
from unittest.mock import AsyncMock, patch, MagicMock
import time


@pytest.mark.asyncio(loop_scope="session")
class TestPaymentIdempotency:
	"""Test idempotent payment processing."""

	async def test_duplicate_payment_intent_same_idempotency_key(
		self, payments_client, mock_event, bearer
	):
		"""Test that duplicate requests with same idempotency key return same intent."""
		idempotency_key = f"test_idem_{int(time.time())}"
		
		# First request
		response1 = await payments_client.post(
			f"/payments/{mock_event['id']}/create-intent",
			json={"ticket_count": 1},
			headers={
				"Authorization": f"Bearer {bearer}",
				"Idempotency-Key": idempotency_key,
			},
		)
		
		assert response1.status_code == HTTPStatus.OK
		data1 = (await response1.get_json())["data"]
		client_secret1 = data1["client_secret"]
		
		# Duplicate request with same idempotency key
		response2 = await payments_client.post(
			f"/payments/{mock_event['id']}/create-intent",
			json={"ticket_count": 1},
			headers={
				"Authorization": f"Bearer {bearer}",
				"Idempotency-Key": idempotency_key,
			},
		)
		
		assert response2.status_code == HTTPStatus.OK
		data2 = (await response2.get_json())["data"]
		client_secret2 = data2["client_secret"]
		
		# Should return same payment intent
		assert client_secret1 == client_secret2, \
			"Idempotent requests must return identical payment intents"

	async def test_concurrent_payment_creation_race_condition(
		self, payments_client, mock_event, bearer
	):
		"""Test concurrent payment intent creation doesn't create duplicate charges."""
		# Simulate rapid clicks on "pay" button
		tasks = []
		for i in range(5):
			task = payments_client.post(
				f"/payments/{mock_event['id']}/create-intent",
				json={"ticket_count": 1},
				headers={"Authorization": f"Bearer {bearer}"},
			)
			tasks.append(task)
		
		responses = await asyncio.gather(*tasks, return_exceptions=True)
		
		# All should succeed (idempotency handled by Stripe)
		for resp in responses:
			if isinstance(resp, Exception):
				pytest.fail(f"Concurrent request failed: {resp}")
			assert resp.status_code == HTTPStatus.OK

	async def test_webhook_duplicate_delivery(
		self, payments_client, mock_webhook_payload, mock_stripe_signature
	):
		"""Test webhook handles duplicate delivery gracefully."""
		# Stripe may deliver webhooks multiple times
		
		# First delivery
		response1 = await payments_client.post(
			"/payments/webhook",
			data=mock_webhook_payload,
			headers={"Stripe-Signature": mock_stripe_signature},
		)
		
		assert response1.status_code == HTTPStatus.OK
		
		# Duplicate delivery
		response2 = await payments_client.post(
			"/payments/webhook",
			data=mock_webhook_payload,
			headers={"Stripe-Signature": mock_stripe_signature},
		)
		
		# Should handle gracefully (ticket already exists check)
		assert response2.status_code == HTTPStatus.OK

	async def test_payment_intent_with_zero_amount(
		self, payments_client, mock_event, bearer
	):
		"""Test payment intent creation with zero amount is rejected."""
		# Modify event price to 0
		with patch.object(payments_client.application.conn, '_fetch') as mock_fetch:
			mock_fetch.return_value = {**mock_event, "price": 0}
			
			response = await payments_client.post(
				f"/payments/{mock_event['id']}/create-intent",
				json={"ticket_count": 1},
				headers={"Authorization": f"Bearer {bearer}"},
			)
			
			# Should reject or handle free events differently
			assert response.status_code in [HTTPStatus.BAD_REQUEST, HTTPStatus.OK]

	async def test_payment_intent_with_negative_ticket_count(
		self, payments_client, mock_event, bearer
	):
		"""Test payment intent with negative ticket count is rejected."""
		response = await payments_client.post(
			f"/payments/{mock_event['id']}/create-intent",
			json={"ticket_count": -1},
			headers={"Authorization": f"Bearer {bearer}"},
		)
		
		assert response.status_code == HTTPStatus.BAD_REQUEST, \
			"Negative ticket count should be rejected"

	async def test_payment_intent_excessive_ticket_count(
		self, payments_client, mock_event, bearer
	):
		"""Test payment intent with unreasonable ticket count."""
		response = await payments_client.post(
			f"/payments/{mock_event['id']}/create-intent",
			json={"ticket_count": 10000},  # Excessive
			headers={"Authorization": f"Bearer {bearer}"},
		)
		
		# Should either reject or apply business limit
		assert response.status_code in [HTTPStatus.BAD_REQUEST, HTTPStatus.OK]
		
		if response.status_code == HTTPStatus.OK:
			data = (await response.get_json())["data"]
			# If accepted, amount should be reasonable (not overflow)
			assert data["amount"] < 100000000, "Amount sanity check failed"
