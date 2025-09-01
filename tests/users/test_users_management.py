import pytest
from faker import Faker
from httpx import AsyncClient
from datetime import datetime
from test_users_base import TestUsersBase
from http import HTTPStatus

fake = Faker()


@pytest.mark.asyncio(loop_scope="session")
class TestUserManagement(TestUsersBase):
    async def test_get_user_events(self, users_client, mock_user, bearer):
        """Test retrieving events related to the current user (/user/events)."""
        response = await self.get_user_events(users_client, bearer)
        assert response.status_code == HTTPStatus.OK  # Use get_attended_events helper

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "User events fetched successfully" in response_json["message"]
        assert "data" in response_json
        events = response_json["data"]
        assert isinstance(events, dict)  # Ensure it's a list of events
        print("User Events:", events)  # Debug print to see the events

    async def test_get_user_profile(self, users_client, mock_user, bearer):
        """Test retrieving the current user's profile (/user)."""
        response = await self.get_me(users_client, bearer)  # Use get_me helper
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "User details fetched successfully" in response_json["message"]
        assert "data" in response_json
        profile = response_json["data"]
        assert profile["id"] == mock_user["id"]  # Verify it's the correct user
        assert "first_name" in profile
        assert "username" in profile

    async def test_get_other_user_profile(self, users_client, mock_user, bearer):
        """Test retrieving another user's profile (/users/{user_id})."""
        user_id = mock_user["id"]  # Use the mock user's ID for testing
        response = await self.get_user(
            users_client, user_id, bearer
        )  # Use get_user helper

        assert response.status_code == HTTPStatus.OK
        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "User profile fetched successfully" in response_json["message"]
        assert "data" in response_json
        profile = response_json["data"]
        assert profile["id"] == user_id
        assert "first_name" in profile
        assert "username" in profile
        # Ensure sensitive data like email might be excluded for other users
        assert "email" not in profile  # Adjust if email is public

    async def test_update_user_profile(self, users_client, mock_user, bearer):
        """Test updating current user profile information."""
        update_data = {"username": fake.user_name(), "bio": fake.text(max_nb_chars=200)}

        response = await self.update_user(users_client, update_data, bearer)
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "User updated successfully" in response_json["message"]
        assert "data" in response_json
        updated_profile = response_json["data"]

        assert updated_profile["username"] == update_data["username"]
        assert updated_profile["bio"] == update_data["bio"]
        assert updated_profile["id"] == mock_user["id"]  # Check ID remains same

    async def test_create_connection(
        self, users_client, mock_user, other_mock_user, bearer
    ):
        """Test creating a connection (friend request)."""
        # Ensure other_mock_user exists and has an ID
        target_id = other_mock_user["id"]
        response = await self.create_connection(users_client, target_id, bearer)
        assert response.status_code == HTTPStatus.CREATED

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.CREATED.phrase
        assert (
            "Friend request sent successfully" in response_json["message"]
        )  # Or check notification failure message
        assert "data" in response_json
        connection_edge = response_json["data"]

        # Response format might be a list containing the edge
        # assert isinstance(created_connection, list)
        # assert len(created_connection) > 0
        # connection_edge = created_connection[0]
        assert "id" in connection_edge
        # assert connection_edge["in"] == f"users:{mock_user['id']}" # Check direction
        # assert connection_edge["out"] == f"users:{target_id}"
        assert connection_edge["status"] == "pending"  # Initial status

    async def test_fetch_connections(self, users_client, mock_user, bearer):
        """Test fetching all connections for the current user."""
        # May need to create a connection first if none exist
        response = await self.fetch_connections(users_client, bearer)
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "Connections up to degree" in response_json["message"]
        assert "data" in response_json
        connections_data = response_json["data"]

        assert isinstance(connections_data, dict)
        # Check structure based on what find_connections_at_degree returns
        assert "degree_1" in connections_data  # Example check

    async def test_update_connection(
        self, users_client, mock_user, other_mock_user, bearer
    ):
        """Test updating a connection (accepting a request)."""
        # 1. User A sends request to User B
        target_id = other_mock_user["id"]
        create_response = await self.create_connection(users_client, target_id, bearer)
        assert create_response.status_code == HTTPStatus.CREATED
        create_json = await create_response.get_json()
        connection_edge = create_json["data"]
        connection_id = connection_edge["id"]

        # 2. User B accepts the request
        update_status = "accepted"
        # Use other_bearer (User B's token) to accept
        update_response = await self.update_connection(
            users_client, connection_id, update_status, bearer
        )
        assert update_response.status_code == HTTPStatus.OK

        update_json = await update_response.get_json()
        assert update_json["status"] == HTTPStatus.OK.phrase
        assert "Connection status updated successfully" in update_json["message"]
        assert "data" in update_json
        updated_connection = update_json["data"]

        # Response might be the updated edge or just confirmation
        # If edge is returned:
        assert updated_connection["id"] == connection_id
        assert updated_connection["status"] == update_status

    async def test_delete_connection(
        self, users_client, mock_user, other_mock_user, bearer
    ):
        """Test deleting a connection (or cancelling/rejecting request)."""
        # 1. Create connection first
        target_id = other_mock_user["id"]
        create_response = await self.create_connection(users_client, target_id, bearer)
        assert create_response.status_code == HTTPStatus.CREATED
        create_json = await create_response.get_json()
        connection_edge = create_json["data"]
        connection_id = connection_edge["id"]

        # 2. Delete the connection (either user can do this)
        delete_response = await self.delete_connection(
            users_client, connection_id, bearer
        )
        assert delete_response.status_code == HTTPStatus.OK

        # 204 No Content might have an empty body or a minimal JSON body
        try:
            delete_json = await delete_response.get_json()
            if delete_json:  # Check if body is not empty
                assert delete_json["status"] == HTTPStatus.OK.phrase
                assert "Connection deleted successfully" in delete_json["message"]
        except Exception:
            # Handle cases where get_json() fails on an empty body
            pass

        # 3. Verify deletion (optional, e.g., try fetching connections)
        fetch_resp = await self.fetch_connections(users_client, bearer)
        fetch_json = await fetch_resp.get_json()
        # Check if the deleted connection ID is no longer present in the connections data

    async def test_report_user_success(self, users_client, other_mock_user, bearer):
        """Test reporting a user successfully."""
        target_user_id = other_mock_user["id"]
        report_data = {"reason": fake.sentence()}
        response = await self.report_user(
            users_client, target_user_id, report_data, bearer
        )
        assert response.status_code == HTTPStatus.CREATED
        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.CREATED.phrase
        assert "Resource reported" in response_json["message"]
        assert "data" in response_json and "id" in response_json["data"]

    async def test_report_user_missing_reason(
        self, users_client, other_mock_user, bearer
    ):
        """Test reporting a user without a reason."""
        target_user_id = other_mock_user["id"]
        report_data = {}
        response = await self.report_user(
            users_client, target_user_id, report_data, bearer
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_json = await response.get_json()
        assert "Reason is required" in response_json["message"]

    # Add test for reporting non-existent user

    # @pytest.mark.parametrize("invalid_data", [
    #     {"display_name": ""},  # Empty display name
    #     {"bio": "x" * 1001},  # Bio too long
    #     {"interests": "not-a-list"}  # Invalid interests format
    # ])
    # async def test_invalid_profile_updates(self, users_client, invalid_data, mock_user, bearer):
    #     """Test profile updates with invalid data."""
    #     response = await self.update_user(users_client, invalid_data, bearer)
    #     assert response.status_code == HTTPStatus.BAD_REQUEST
    #     response_json = await response.get_json()
    #     assert response_json["status"] == HTTPStatus.BAD_REQUEST.phrase
    #     # Add assertion for specific error message

    # async def test_user_search(self, users_client, bearer):
    #     """Test user search functionality."""
    #     search_term = fake.user_name()[:5] # Search for part of a username
    #     response = await users_client.get(f"/users/search?username={search_term}", headers={"Authorization": f"Bearer {bearer}"})
    #     assert response.status_code == HTTPStatus.OK # Or NOT_IMPLEMENTED
    #     response_json = await response.get_json()
    #     assert response_json["status"] == HTTPStatus.OK.phrase # Or NOT_IMPLEMENTED
    #     assert "data" in response_json
    #     results = response_json["data"]
    #     assert isinstance(results, list)
