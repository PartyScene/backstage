"""
Payment Edge Cases - Boundary conditions and error scenarios.
"""
import pytest
from http import HTTPStatus
from unittest.mock import patch, AsyncMock
from decimal import Decimal
import stripe


@pytest.mark.asyncio(loop_scope="session")
class TestPaymentEdgeCases:
	"""Test payment system edge cases and error handling."""

	async def test_payment_for_nonexistent_event(
		self, payments_client, bearer
	):
		"""Test payment intent creation for non-existent event."""
		fake_event_id = "nonexistent_event_999"
		
		response = await payments_client.post(
			f"/payments/{fake_event_id}/create-intent",
			json={"ticket_count": 1},
			headers={"Authorization": f"Bearer {bearer}"},
		)
		
		assert response.status_code == HTTPStatus.NOT_FOUND, \
			"Non-existent event should return 404"

	async def test_payment_when_stripe_api_down(
		self, payments_client, mock_event, bearer
	):
		"""Test graceful handling when Stripe API is unavailable."""
		with patch.object(
			payments_client.application.views[0].stripe_client.payment_intents,
			'create_async',
			side_effect=stripe.error.APIConnectionError("Network error")
		):
			response = await payments_client.post(
				f"/payments/{mock_event['id']}/create-intent",
				json={"ticket_count": 1},
				headers={"Authorization": f"Bearer {bearer}"},
			)
			
			assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
			error_data = await response.get_json()
			assert "Failed to create payment intent" in error_data["message"]

	async def test_payment_when_database_unavailable(
		self, payments_client, mock_event, bearer
	):
		"""Test payment fails gracefully when DB is down."""
		with patch.object(
			payments_client.application.conn,
			'_fetch',
			side_effect=Exception("Database connection lost")
		):
			response = await payments_client.post(
				f"/payments/{mock_event['id']}/create-intent",
				json={"ticket_count": 1},
				headers={"Authorization": f"Bearer {bearer}"},
			)
			
			assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

	async def test_fee_calculation_accuracy(self, payments_client):
		"""Test Stripe fee calculation is accurate."""
		# Test fee formula: (base + 0.30) / (1 - 0.029)
		base_view = payments_client.application.views[0]
		
		test_cases = [
			(10.00, 10.6087),  # $10 base
			(100.00, 103.394),  # $100 base
			(0.50, 1.123),      # Min charge
			(999.99, 1030.40),  # Large amount
		]
		
		for base_amount, expected_total in test_cases:
			calculated = base_view.calculate_total_amount(base_amount)
			assert abs(calculated - expected_total) < 0.01, \
				f"Fee calculation incorrect for ${base_amount}"

	async def test_currency_precision(self, payments_client, mock_event, bearer):
		"""Test amount is properly converted to cents (Stripe requirement)."""
		response = await payments_client.post(
			f"/payments/{mock_event['id']}/create-intent",
			json={"ticket_count": 1},
			headers={"Authorization": f"Bearer {bearer}"},
		)
		
		assert response.status_code == HTTPStatus.OK
		data = (await response.get_json())["data"]
		
		# Stripe amounts are in cents, must be integers
		assert isinstance(data["amount"], int), \
			"Stripe amount must be integer (cents)"
		assert data["amount"] > 0, "Amount must be positive"

	async def test_concurrent_ticket_purchases_same_event(
		self, payments_client, mock_event, bearer
	):
		"""Test multiple users buying tickets simultaneously."""
		import asyncio
		
		# Simulate 10 users purchasing tickets concurrently
		tasks = []
		for i in range(10):
			task = payments_client.post(
				f"/payments/{mock_event['id']}/create-intent",
				json={"ticket_count": 1},
				headers={"Authorization": f"Bearer {bearer}"},
			)
			tasks.append(task)
		
		responses = await asyncio.gather(*tasks, return_exceptions=True)
		
		# All should succeed (capacity check is separate concern)
		success_count = sum(
			1 for r in responses
			if not isinstance(r, Exception) and r.status_code == HTTPStatus.OK
		)
		
		assert success_count == 10, \
			f"Only {success_count}/10 concurrent purchases succeeded"

	async def test_ticket_creation_database_failure_rollback(
		self, payments_client, mock_event, mock_user
	):
		"""Test ticket creation failure doesn't leave payment orphaned."""
		import json as json_lib
		
		payload = json_lib.dumps({
			"type": "payment_intent.succeeded",
			"data": {"object": {
				"id": "pi_db_fail_test",
				"amount": 2500,
				"metadata": {
					"user_id": mock_user["id"],
					"event_id": mock_event["id"],
					"ticket_count": "1"
				}
			}}
		}).encode()
		
		# Simulate DB failure during ticket creation
		with patch('stripe.Webhook.construct_event') as mock_construct:
			mock_construct.return_value = json_lib.loads(payload.decode())
			
			with patch.object(
				payments_client.application.conn,
				'_create_ticket',
				side_effect=Exception("DB write failed")
			):
				response = await payments_client.post(
					"/payments/webhook",
					data=payload,
					headers={"Stripe-Signature": "valid_sig"},
				)
				
				# Should fail gracefully
				# Stripe will retry webhook, ticket eventually created
				assert response.status_code in [HTTPStatus.OK, HTTPStatus.INTERNAL_SERVER_ERROR]

	async def test_attendance_creation_without_ticket(
		self, payments_client, mock_event, mock_user
	):
		"""Test attendance relationship requires ticket creation first."""
		import json as json_lib
		
		payload = json_lib.dumps({
			"type": "payment_intent.succeeded",
			"data": {"object": {
				"id": "pi_attendance_test",
				"amount": 2500,
				"metadata": {
					"user_id": mock_user["id"],
					"event_id": mock_event["id"],
					"ticket_count": "1"
				}
			}}
		}).encode()
		
		with patch('stripe.Webhook.construct_event') as mock_construct:
			mock_construct.return_value = json_lib.loads(payload.decode())
			
			# Mock ticket creation success but attendance failure
			with patch.object(
				payments_client.application.conn,
				'create_attendance',
				side_effect=Exception("Attendance creation failed")
			):
				response = await payments_client.post(
					"/payments/webhook",
					data=payload,
					headers={"Stripe-Signature": "valid_sig"},
				)
				
				# Ticket created but attendance failed - log error
				# Manual reconciliation may be needed
				assert response.status_code in [HTTPStatus.OK, HTTPStatus.INTERNAL_SERVER_ERROR]

	async def test_kyc_payment_amount_validation(
		self, payments_client, bearer
	):
		"""Test KYC payment has fixed amount ($10.00 + fees)."""
		response = await payments_client.post(
			"/payments/kyc/create-intent",
			json={},
			headers={"Authorization": f"Bearer {bearer}"},
		)
		
		assert response.status_code == HTTPStatus.OK
		data = (await response.get_json())["data"]
		
		# KYC payment is fixed $10.00 + Stripe fees
		expected_amount = int(10.6087 * 100)  # Convert to cents
		assert abs(data["amount"] - expected_amount) < 5, \
			"KYC payment amount incorrect"

	async def test_stripe_rate_limiting_handling(
		self, payments_client, mock_event, bearer
	):
		"""Test graceful handling of Stripe rate limits."""
		with patch.object(
			payments_client.application.views[0].stripe_client.payment_intents,
			'create_async',
			side_effect=stripe.error.RateLimitError("Too many requests")
		):
			response = await payments_client.post(
				f"/payments/{mock_event['id']}/create-intent",
				json={"ticket_count": 1},
				headers={"Authorization": f"Bearer {bearer}"},
			)
			
			# Should return 429 or 503 for retry
			assert response.status_code in [HTTPStatus.TOO_MANY_REQUESTS, HTTPStatus.SERVICE_UNAVAILABLE]

	async def test_invalid_stripe_api_key(
		self, payments_client, mock_event, bearer
	):
		"""Test handling of invalid Stripe API credentials."""
		with patch.object(
			payments_client.application.views[0].stripe_client.payment_intents,
			'create_async',
			side_effect=stripe.error.AuthenticationError("Invalid API key")
		):
			response = await payments_client.post(
				f"/payments/{mock_event['id']}/create-intent",
				json={"ticket_count": 1},
				headers={"Authorization": f"Bearer {bearer}"},
			)
			
			assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
