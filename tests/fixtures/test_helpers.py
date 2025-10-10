"""
Test Helper Functions - Reusable utilities for tests.
Reduces code duplication and improves test readability.
"""
import asyncio
import hmac
import hashlib
import time
import json as json_lib
from typing import Dict, Any, Optional
from faker import Faker
from datetime import datetime, timedelta


fake = Faker()


class TestHelpers:
	"""Collection of test helper methods."""

	@staticmethod
	def generate_stripe_signature(payload: bytes, secret: str, timestamp: int = None) -> str:
		"""Generate valid Stripe webhook signature."""
		if timestamp is None:
			timestamp = int(time.time())
		
		signed_payload = f"{timestamp}.{payload.decode()}"
		signature = hmac.new(
			secret.encode(),
			signed_payload.encode(),
			hashlib.sha256
		).hexdigest()
		
		return f"t={timestamp},v1={signature}"

	@staticmethod
	def create_mock_event(event_id: str = None, **overrides) -> Dict[str, Any]:
		"""Create mock event data with realistic values."""
		event_id = event_id or fake.uuid4()
		
		default_event = {
			"id": event_id,
			"title": fake.catch_phrase(),
			"description": fake.text(),
			"location": fake.address(),
			"price": fake.random_int(min=10, max=100),
			"host": "test_user",
			"time": (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z",
			"coordinates": [float(fake.longitude()), float(fake.latitude())],
			"categories": ["test", "integration"],
			"is_private": False,
			"is_free": False,
			"status": "scheduled",
		}
		
		default_event.update(overrides)
		return default_event

	@staticmethod
	def create_mock_user(user_id: str = None, **overrides) -> Dict[str, Any]:
		"""Create mock user data with realistic values."""
		user_id = user_id or fake.uuid4()
		
		default_user = {
			"id": user_id,
			"email": fake.email(),
			"first_name": fake.first_name(),
			"last_name": fake.last_name(),
			"username": fake.user_name(),
			"password": "TestPass123!",
			"confirm_password": "TestPass123!",
		}
		
		default_user.update(overrides)
		return default_user

	@staticmethod
	def create_stripe_payment_intent_success_webhook(
		user_id: str,
		event_id: str,
		ticket_count: int = 1,
		amount: int = 2500
	) -> bytes:
		"""Create Stripe payment_intent.succeeded webhook payload."""
		payload = {
			"type": "payment_intent.succeeded",
			"data": {
				"object": {
					"id": f"pi_test_{fake.uuid4()}",
					"amount": amount,
					"currency": "usd",
					"metadata": {
						"user_id": user_id,
						"event_id": event_id,
						"ticket_count": str(ticket_count)
					}
				}
			}
		}
		return json_lib.dumps(payload).encode()

	@staticmethod
	def create_rabbitmq_message(filename: str, creator: str, **metadata) -> Dict[str, Any]:
		"""Create RabbitMQ message for media upload."""
		message = {
			"filename": filename,
			"type": "image/jpeg",
			"creator": creator,
		}
		message.update(metadata)
		return message

	@staticmethod
	async def wait_for_condition(
		condition_func,
		timeout: float = 5.0,
		interval: float = 0.1
	) -> bool:
		"""Wait for async condition to become true."""
		start_time = time.time()
		
		while time.time() - start_time < timeout:
			if await condition_func():
				return True
			await asyncio.sleep(interval)
		
		return False

	@staticmethod
	def assert_response_structure(
		response_data: Dict[str, Any],
		required_fields: list
	) -> None:
		"""Assert response has required fields."""
		for field in required_fields:
			assert field in response_data, \
				f"Response missing required field: {field}"

	@staticmethod
	def assert_valid_timestamp(timestamp_str: str) -> None:
		"""Assert timestamp is valid ISO format."""
		try:
			datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
		except ValueError as e:
			pytest.fail(f"Invalid timestamp format: {timestamp_str} - {e}")

	@staticmethod
	def assert_valid_uuid(uuid_str: str) -> None:
		"""Assert string is valid UUID."""
		import uuid
		try:
			uuid.UUID(uuid_str)
		except ValueError:
			pytest.fail(f"Invalid UUID: {uuid_str}")

	@staticmethod
	def assert_http_error(response, expected_status: int, expected_message_contains: str = None):
		"""Assert HTTP error response structure."""
		assert response.status_code == expected_status, \
			f"Expected status {expected_status}, got {response.status_code}"
		
		if expected_message_contains:
			response_data = response.get_json() if hasattr(response, 'get_json') else {}
			message = response_data.get("message", "")
			assert expected_message_contains.lower() in message.lower(), \
				f"Expected message to contain '{expected_message_contains}', got '{message}'"

	@staticmethod
	async def simulate_database_failure(mock_conn, method_name: str, exception: Exception):
		"""Simulate database failure for testing error handling."""
		import unittest.mock
		original_method = getattr(mock_conn, method_name)
		
		with unittest.mock.patch.object(mock_conn, method_name, side_effect=exception):
			yield

	@staticmethod
	def create_large_payload(size_mb: int = 10) -> bytes:
		"""Create large binary payload for upload testing."""
		return b"0" * (size_mb * 1024 * 1024)

	@staticmethod
	def sanitize_test_data(data: Dict[str, Any]) -> Dict[str, Any]:
		"""Remove sensitive data from test output."""
		sensitive_fields = ["password", "token", "secret", "api_key"]
		sanitized = data.copy()
		
		for field in sensitive_fields:
			if field in sanitized:
				sanitized[field] = "***REDACTED***"
		
		return sanitized
