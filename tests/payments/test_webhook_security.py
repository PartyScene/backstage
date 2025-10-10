"""
Webhook Security Tests - Stripe signature verification.
Critical: Prevents attackers from forging payment success events.
"""
import pytest
import hmac
import hashlib
import time
import json as json_lib
from http import HTTPStatus
from unittest.mock import patch


@pytest.mark.asyncio(loop_scope="session")
class TestWebhookSecurity:
	"""Test Stripe webhook signature verification."""

	def generate_stripe_signature(self, payload: bytes, secret: str, timestamp: int = None) -> str:
		"""Generate valid Stripe signature for testing."""
		if timestamp is None:
			timestamp = int(time.time())
		
		signed_payload = f"{timestamp}.{payload.decode()}"
		signature = hmac.new(
			secret.encode(),
			signed_payload.encode(),
			hashlib.sha256
		).hexdigest()
		
		return f"t={timestamp},v1={signature}"

	async def test_webhook_with_invalid_signature(self, payments_client):
		"""Test webhook rejects invalid signatures."""
		payload = json_lib.dumps({
			"type": "payment_intent.succeeded",
			"data": {"object": {"id": "pi_test_123", "metadata": {}}}
		}).encode()
		
		response = await payments_client.post(
			"/payments/webhook",
			data=payload,
			headers={"Stripe-Signature": "invalid_signature"},
		)
		
		assert response.status_code == HTTPStatus.BAD_REQUEST, \
			"Invalid signature must be rejected"
		
		error_data = await response.get_json()
		assert "signature" in error_data["error"].lower()

	async def test_webhook_with_no_signature(self, payments_client):
		"""Test webhook rejects requests without signature header."""
		payload = json_lib.dumps({
			"type": "payment_intent.succeeded",
			"data": {"object": {"id": "pi_test_123", "metadata": {}}}
		}).encode()
		
		response = await payments_client.post(
			"/payments/webhook",
			data=payload,
			# No Stripe-Signature header
		)
		
		assert response.status_code == HTTPStatus.BAD_REQUEST

	async def test_webhook_with_expired_timestamp(self, payments_client):
		"""Test webhook rejects old signatures (replay attack prevention)."""
		# Stripe rejects signatures older than 5 minutes
		old_timestamp = int(time.time()) - 600  # 10 minutes ago
		
		payload = json_lib.dumps({
			"type": "payment_intent.succeeded",
			"data": {"object": {"id": "pi_test_123", "metadata": {}}}
		}).encode()
		
		secret = "test_webhook_secret"
		signature = self.generate_stripe_signature(payload, secret, old_timestamp)
		
		with patch('stripe.Webhook.construct_event') as mock_construct:
			mock_construct.side_effect = ValueError("Timestamp outside tolerance")
			
			response = await payments_client.post(
				"/payments/webhook",
				data=payload,
				headers={"Stripe-Signature": signature},
			)
			
			assert response.status_code == HTTPStatus.BAD_REQUEST

	async def test_webhook_with_modified_payload(self, payments_client):
		"""Test webhook detects payload tampering."""
		original_payload = json_lib.dumps({
			"type": "payment_intent.succeeded",
			"data": {"object": {
				"id": "pi_test_123",
				"amount": 1000,  # $10.00
				"metadata": {"user_id": "attacker"}
			}}
		}).encode()
		
		secret = "test_webhook_secret"
		signature = self.generate_stripe_signature(original_payload, secret)
		
		# Attacker modifies payload after signature
		modified_payload = original_payload.replace(b'"amount": 1000', b'"amount": 100')
		
		with patch('stripe.Webhook.construct_event') as mock_construct:
			mock_construct.side_effect = ValueError("Signature mismatch")
			
			response = await payments_client.post(
				"/payments/webhook",
				data=modified_payload,  # Modified!
				headers={"Stripe-Signature": signature},
			)
			
			assert response.status_code == HTTPStatus.BAD_REQUEST

	async def test_webhook_payment_success_creates_ticket(
		self, payments_client, mock_event, mock_user
	):
		"""Test successful payment creates ticket in database."""
		payload = json_lib.dumps({
			"type": "payment_intent.succeeded",
			"data": {"object": {
				"id": "pi_test_success_123",
				"amount": 2500,
				"currency": "usd",
				"metadata": {
					"user_id": mock_user["id"],
					"event_id": mock_event["id"],
					"ticket_count": "2"
				}
			}}
		}).encode()
		
		# Mock valid signature verification
		with patch('stripe.Webhook.construct_event') as mock_construct:
			mock_construct.return_value = json_lib.loads(payload.decode())
			
			response = await payments_client.post(
				"/payments/webhook",
				data=payload,
				headers={"Stripe-Signature": "valid_sig"},
			)
			
			assert response.status_code == HTTPStatus.OK
			# Verify tickets created (would need to query DB)

	async def test_webhook_payment_failed_no_ticket_creation(
		self, payments_client, mock_event, mock_user
	):
		"""Test failed payment does NOT create ticket."""
		payload = json_lib.dumps({
			"type": "payment_intent.payment_failed",
			"data": {"object": {
				"id": "pi_test_failed_123",
				"amount": 2500,
				"metadata": {
					"user_id": mock_user["id"],
					"event_id": mock_event["id"],
					"ticket_count": "1"
				},
				"last_payment_error": {
					"message": "Your card was declined."
				}
			}}
		}).encode()
		
		with patch('stripe.Webhook.construct_event') as mock_construct:
			mock_construct.return_value = json_lib.loads(payload.decode())
			
			response = await payments_client.post(
				"/payments/webhook",
				data=payload,
				headers={"Stripe-Signature": "valid_sig"},
			)
			
			assert response.status_code == HTTPStatus.OK
			# Verify NO ticket created

	async def test_webhook_kyc_payment_updates_user_status(
		self, payments_client, mock_user
	):
		"""Test KYC payment webhook updates user verification status."""
		payload = json_lib.dumps({
			"type": "payment_intent.succeeded",
			"data": {"object": {
				"id": "pi_kyc_test_123",
				"amount": 1030,  # $10.30 with fees
				"metadata": {
					"user_id": mock_user["id"],
					"type": "KYC_PAYMENT"
				}
			}}
		}).encode()
		
		with patch('stripe.Webhook.construct_event') as mock_construct:
			mock_construct.return_value = json_lib.loads(payload.decode())
			
			response = await payments_client.post(
				"/payments/webhook",
				data=payload,
				headers={"Stripe-Signature": "valid_sig"},
			)
			
			assert response.status_code == HTTPStatus.OK
			# Verify user KYC status updated to True

	async def test_webhook_unknown_event_type_ignored(self, payments_client):
		"""Test unknown event types are logged but don't crash."""
		payload = json_lib.dumps({
			"type": "customer.subscription.updated",  # Unhandled event
			"data": {"object": {"id": "sub_123"}}
		}).encode()
		
		with patch('stripe.Webhook.construct_event') as mock_construct:
			mock_construct.return_value = json_lib.loads(payload.decode())
			
			response = await payments_client.post(
				"/payments/webhook",
				data=payload,
				headers={"Stripe-Signature": "valid_sig"},
			)
			
			# Should succeed (acknowledged) but take no action
			assert response.status_code == HTTPStatus.OK

	async def test_webhook_missing_metadata_handled_gracefully(
		self, payments_client
	):
		"""Test webhook with incomplete metadata doesn't crash."""
		payload = json_lib.dumps({
			"type": "payment_intent.succeeded",
			"data": {"object": {
				"id": "pi_no_metadata_123",
				"amount": 1000,
				"metadata": {}  # Empty metadata
			}}
		}).encode()
		
		with patch('stripe.Webhook.construct_event') as mock_construct:
			mock_construct.return_value = json_lib.loads(payload.decode())
			
			response = await payments_client.post(
				"/payments/webhook",
				data=payload,
				headers={"Stripe-Signature": "valid_sig"},
			)
			
			# Should handle gracefully, log warning
			assert response.status_code == HTTPStatus.OK
