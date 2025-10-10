"""
SQL Injection Prevention Tests - Parameterized query validation.
Critical security: Ensures user input cannot modify query logic.
"""
import pytest
from http import HTTPStatus


@pytest.mark.security
@pytest.mark.asyncio(loop_scope="session")
class TestSQLInjectionPrevention:
	"""Test protection against SQL injection attacks."""

	async def test_login_email_sql_injection(self, auth_client):
		"""Test SQL injection via email field in login."""
		malicious_emails = [
			"admin' OR '1'='1",
			"admin'--",
			"admin' OR 1=1--",
			"'; DROP TABLE users--",
			"admin' UNION SELECT * FROM credentials--",
			"' OR '1'='1' /*",
		]
		
		for email in malicious_emails:
			response = await auth_client.post(
				"/auth/login",
				json={"email": email, "password": "anything"}
			)
			
			# Should not bypass authentication or crash
			assert response.status_code == HTTPStatus.UNAUTHORIZED, \
				f"SQL injection attempt not blocked: {email}"

	async def test_search_username_sql_injection(self, users_client, bearer):
		"""Test SQL injection via search queries."""
		malicious_queries = [
			"admin' OR '1'='1",
			"'; DELETE FROM users WHERE 'x'='x",
			"') OR ('1'='1",
			"admin%' AND 1=1--",
		]
		
		for query in malicious_queries:
			response = await users_client.get(
				f"/users/search?username={query}",
				headers={"Authorization": f"Bearer {bearer}"}
			)
			
			# Should not execute malicious SQL
			assert response.status_code in [
				HTTPStatus.OK,
				HTTPStatus.NOT_FOUND,
				HTTPStatus.BAD_REQUEST
			]

	async def test_event_id_sql_injection(self, events_client):
		"""Test SQL injection via event ID parameter."""
		malicious_ids = [
			"1' OR '1'='1",
			"1; DROP TABLE events--",
			"1' UNION SELECT * FROM users--",
		]
		
		for event_id in malicious_ids:
			response = await events_client.get(f"/events/{event_id}")
			
			# Should safely handle as invalid ID
			assert response.status_code in [
				HTTPStatus.NOT_FOUND,
				HTTPStatus.BAD_REQUEST
			]

	async def test_registration_sql_injection(self, auth_client):
		"""Test SQL injection during user registration."""
		malicious_data = {
			"email": "test@example.com",
			"username": "admin' OR '1'='1--",
			"password": "TestPass123",
			"confirm_password": "TestPass123",
			"first_name": "'; DROP TABLE users--",
			"last_name": "Test",
		}
		
		response = await auth_client.post(
			"/auth/register",
			json=malicious_data
		)
		
		# Should not execute SQL injection
		assert response.status_code in [
			HTTPStatus.CREATED,
			HTTPStatus.BAD_REQUEST,
			HTTPStatus.CONFLICT
		]

	async def test_update_user_sql_injection(self, users_client, bearer):
		"""Test SQL injection in user update."""
		malicious_update = {
			"first_name": "'; UPDATE users SET role='admin'--",
			"bio": "' OR '1'='1",
		}
		
		response = await users_client.patch(
			"/user",
			json=malicious_update,
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		# Should sanitize or reject
		assert response.status_code in [
			HTTPStatus.OK,
			HTTPStatus.BAD_REQUEST
		]

	async def test_event_filter_sql_injection(self, events_client):
		"""Test SQL injection via event filter parameters."""
		response = await events_client.get(
			"/events?category=' OR '1'='1&status='; DROP TABLE events--"
		)
		
		assert response.status_code in [
			HTTPStatus.OK,
			HTTPStatus.BAD_REQUEST
		]

	async def test_order_by_sql_injection(self, events_client):
		"""Test SQL injection via ORDER BY clause."""
		malicious_sorts = [
			"price; DROP TABLE events--",
			"(SELECT * FROM users)",
			"1,2,3 UNION SELECT * FROM credentials",
		]
		
		for sort in malicious_sorts:
			response = await events_client.get(
				f"/events?sort={sort}"
			)
			
			# Should not execute injection
			assert response.status_code in [
				HTTPStatus.OK,
				HTTPStatus.BAD_REQUEST
			]


@pytest.mark.security
@pytest.mark.asyncio(loop_scope="session")
class TestXSSPrevention:
	"""Test protection against Cross-Site Scripting attacks."""

	async def test_xss_in_event_description(self, events_client, bearer, mock_event):
		"""Test XSS payload in event description."""
		xss_payloads = [
			"<script>alert('XSS')</script>",
			"<img src=x onerror=alert('XSS')>",
			"<iframe src='javascript:alert(1)'></iframe>",
			"javascript:alert(document.cookie)",
		]
		
		for payload in xss_payloads:
			event_data = {**mock_event, "description": payload}
			
			# Create event with XSS payload
			response = await events_client.post(
				"/events",
				json=event_data,
				headers={"Authorization": f"Bearer {bearer}"}
			)
			
			if response.status_code == HTTPStatus.CREATED:
				# Fetch event back
				event_id = (await response.get_json())["data"]["id"]
				fetch_response = await events_client.get(f"/events/{event_id}")
				
				# XSS should be sanitized or escaped
				event = (await fetch_response.get_json())["data"]["event"]
				assert "<script>" not in event["description"], \
					"XSS payload not sanitized"

	async def test_xss_in_user_profile(self, users_client, bearer):
		"""Test XSS payload in user bio."""
		xss_bio = {
			"bio": "<script>alert('Hacked')</script>"
		}
		
		response = await users_client.patch(
			"/user",
			json=xss_bio,
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		if response.status_code == HTTPStatus.OK:
			# Fetch profile
			profile_response = await users_client.get(
				"/user",
				headers={"Authorization": f"Bearer {bearer}"}
			)
			
			user_data = (await profile_response.get_json())["data"]
			# XSS should be sanitized
			assert "<script>" not in user_data.get("bio", "")


@pytest.mark.security
@pytest.mark.asyncio(loop_scope="session")
class TestCSRFPrevention:
	"""Test CSRF protection mechanisms."""

	async def test_state_changing_endpoints_require_token(self, events_client):
		"""Test POST/PUT/DELETE require valid authentication."""
		# Attempt state-changing operation without auth
		response = await events_client.post(
			"/events",
			json={"title": "Unauthorized Event"}
		)
		
		assert response.status_code == HTTPStatus.UNAUTHORIZED

	async def test_get_requests_dont_change_state(self, users_client, bearer):
		"""Test GET requests are safe (no side effects)."""
		# GET should never delete, update, or create
		# This is a design principle test
		
		response = await users_client.get(
			"/user/delete",  # If this endpoint exists, it's bad design
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		# Should return 404 or 405 (method not allowed)
		assert response.status_code in [
			HTTPStatus.NOT_FOUND,
			HTTPStatus.METHOD_NOT_ALLOWED
		]
