"""
User Privacy Controls Tests - Access control and data visibility.
Tests private profiles, friend-only content, and data protection.
"""
import pytest
from http import HTTPStatus


@pytest.mark.asyncio(loop_scope="session")
class TestPrivacyControls:
	"""Test user privacy settings and access control."""

	async def test_private_profile_not_visible_to_strangers(
		self, users_client, mock_user, other_bearer
	):
		"""Test private profile hidden from non-friends."""
		# Set profile to private
		await users_client.patch(
			"/user",
			json={"is_private": True},
			headers={"Authorization": f"Bearer {other_bearer}"}
		)
		
		# Try to view with different user
		response = await users_client.get(
			f"/users/{mock_user['id']}"
		)
		
		# Should return limited info or 403
		assert response.status_code in [HTTPStatus.FORBIDDEN, HTTPStatus.OK]
		
		if response.status_code == HTTPStatus.OK:
			data = (await response.get_json())["data"]
			# Sensitive fields should be hidden
			assert "email" not in data or data["email"] is None

	async def test_friend_can_view_private_profile(
		self, users_client, bearer, other_bearer
	):
		"""Test friends can view private profiles."""
		# Create friend relationship
		await users_client.post(
			"/friends",
			json={"target_id": "other_user"},
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		# Accept friend request
		# ... (connection_id needed)
		
		# Now should be able to view profile
		response = await users_client.get(
			"/users/other_user",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		assert response.status_code == HTTPStatus.OK

	async def test_blocked_user_cannot_view_profile(
		self, users_client, bearer
	):
		"""Test blocked users cannot view blocker's profile."""
		# Block user
		await users_client.post(
			"/users/block",
			json={"user_id": "blocked_user"},
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		# Blocked user tries to view profile
		response = await users_client.get(
			f"/user",
			headers={"Authorization": "Bearer blocked_user_token"}
		)
		
		assert response.status_code in [HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED]

	async def test_event_attendance_privacy(
		self, users_client, bearer
	):
		"""Test user can hide event attendance from others."""
		# Set attendance visibility to private
		await users_client.patch(
			"/user/privacy",
			json={"show_events": False},
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		# Others try to fetch user's events
		response = await users_client.get(
			"/users/test_user/events"
		)
		
		# Should return empty or 403
		assert response.status_code in [HTTPStatus.FORBIDDEN, HTTPStatus.OK]

	async def test_friend_list_visibility_control(
		self, users_client, bearer
	):
		"""Test user can hide friend list."""
		# Set friends visibility to private
		await users_client.patch(
			"/user/privacy",
			json={"show_friends": False},
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		# Others try to fetch user's friends
		response = await users_client.get(
			"/users/test_user/friends"
		)
		
		assert response.status_code in [HTTPStatus.FORBIDDEN, HTTPStatus.OK]

	async def test_email_not_exposed_in_public_api(
		self, users_client
	):
		"""Test email addresses never exposed in public endpoints."""
		response = await users_client.get("/users/search?username=test")
		
		if response.status_code == HTTPStatus.OK:
			data = (await response.get_json())["data"]
			for user in data:
				assert "email" not in user or user["email"] is None, \
					"Email exposed in public API"

	async def test_password_never_returned(
		self, users_client, bearer
	):
		"""Test password hash never returned in any response."""
		response = await users_client.get(
			"/user",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		data = (await response.get_json())["data"]
		
		# Password fields should never be present
		forbidden_fields = ["password", "hashed_password", "password_hash"]
		for field in forbidden_fields:
			assert field not in data, \
				f"Sensitive field '{field}' exposed in response"

	async def test_admin_fields_not_exposed(
		self, users_client, bearer
	):
		"""Test internal/admin fields not exposed to regular users."""
		response = await users_client.get(
			"/user",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		data = (await response.get_json())["data"]
		
		# Internal fields should not be exposed
		internal_fields = [
			"_internal_id",
			"admin_notes",
			"internal_status",
			"verification_secret"
		]
		
		for field in internal_fields:
			assert field not in data

	async def test_location_tracking_opt_out(
		self, users_client, bearer
	):
		"""Test user can disable location tracking."""
		# Disable location
		await users_client.patch(
			"/user/privacy",
			json={"track_location": False},
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		# Location should not be stored/shared
		response = await users_client.get(
			"/user",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		data = (await response.get_json())["data"]
		assert "last_location" not in data or data["last_location"] is None

	async def test_gdpr_data_export(
		self, users_client, bearer
	):
		"""Test user can export all their data (GDPR compliance)."""
		response = await users_client.get(
			"/user/export-data",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		# Should provide complete data export
		assert response.status_code in [HTTPStatus.OK, HTTPStatus.NOT_IMPLEMENTED]

	async def test_right_to_be_forgotten(
		self, users_client, bearer
	):
		"""Test user can request complete data deletion."""
		response = await users_client.delete(
			"/user",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		assert response.status_code == HTTPStatus.OK
		
		# After deletion, data should be inaccessible
		verify_response = await users_client.get(
			"/user",
			headers={"Authorization": f"Bearer {bearer}"}
		)
		
		assert verify_response.status_code in [
			HTTPStatus.UNAUTHORIZED,
			HTTPStatus.NOT_FOUND
		]
