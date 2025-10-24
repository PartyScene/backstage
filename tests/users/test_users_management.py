import pytest
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from faker import Faker
from httpx import AsyncClient
from datetime import datetime
from test_users_base import TestUsersBase
from http import HTTPStatus

fake = Faker()


@pytest.mark.asyncio(loop_scope="session")
class TestUserManagement(TestUsersBase):
    """Streamlined user management tests following TDD best practices."""
    async def test_user_events_retrieval_succeeds_when_authenticated(self, users_client, mock_user, bearer):
        """Should retrieve user events successfully when authenticated user makes request."""
        # Act
        response = await self.get_user_events(users_client, bearer)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        self.assert_successful_response(response_json)
        assert "User events fetched successfully" in response_json["message"]
        assert isinstance(response_json["data"], dict)

    async def test_current_user_profile_retrieval_succeeds_when_authenticated(self, users_client, mock_user, bearer):
        """Should retrieve current user profile successfully when authenticated."""
        # Act
        response = await self.get_me(users_client, bearer)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        self.assert_successful_response(response_json)
        assert "User details fetched successfully" in response_json["message"]
        
        profile = response_json["data"]
        self.assert_required_fields(profile, ["id", "first_name", "username"])
        assert profile["id"] == mock_user["id"]

    async def test_other_user_profile_retrieval_succeeds_excluding_private_data(self, users_client, mock_user, bearer):
        """Should retrieve other user's profile successfully but exclude private data."""
        # Arrange
        user_id = mock_user["id"]
        
        # Act
        response = await self.get_user(users_client, user_id, bearer)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        self.assert_successful_response(response_json)
        assert "User profile fetched successfully" in response_json["message"]
        
        profile = response_json["data"]
        self.assert_required_fields(profile, ["id", "first_name", "username"])
        assert profile["id"] == user_id
        # Private data should be excluded
        assert "email" not in profile

    async def test_user_profile_update_succeeds_when_valid_data_provided(self, users_client, mock_user, bearer):
        """Should update user profile successfully when valid data is provided."""
        # Arrange
        update_data = {"username": fake.user_name(), "bio": fake.text(max_nb_chars=200)}
        
        # Act
        updated_profile = await self.update_resource_successfully(
            users_client, "/user", update_data, bearer
        )
        
        # Assert
        assert updated_profile["username"] == update_data["username"]
        assert updated_profile["bio"] == update_data["bio"]
        assert updated_profile["id"] == mock_user["id"]

    async def test_friend_request_creation_succeeds_when_target_user_exists(self, users_client, mock_user, other_mock_user, bearer):
        """Should create friend request successfully when target user exists."""
        # Arrange
        target_id = other_mock_user["id"]
        
        # Act
        response = await self.create_connection(users_client, target_id, bearer)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.CREATED
        self.assert_resource_created(response_json)
        assert "Friend request sent successfully" in response_json["message"]
        
        connection_edge = response_json["data"]
        self.assert_required_fields(connection_edge, ["id", "status"])
        assert connection_edge["status"] == "pending"

    async def test_connections_retrieval_succeeds_when_authenticated(self, users_client, mock_user, bearer):
        """Should retrieve connections successfully when authenticated user makes request."""
        # Act
        response = await self.fetch_connections(users_client, bearer)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        self.assert_successful_response(response_json)
        assert "Connections up to degree" in response_json["message"]
        
        connections_data = response_json["data"]
        assert isinstance(connections_data, dict)
        assert "degree_1" in connections_data

    async def test_connection_status_update_succeeds_when_valid_status_provided(self, users_client, mock_user, other_mock_user, bearer):
        """Should update connection status successfully when valid status is provided."""
        # Note: This test requires complex multi-user flow - needs refactoring for proper isolation
        pytest.skip("Complex connection update test - requires multi-user test isolation")

    async def test_connection_deletion_succeeds_when_valid_connection_id_provided(self, users_client, mock_user, other_mock_user, bearer):
        """Should delete connection successfully when valid connection ID is provided."""
        # Note: This test requires complex multi-user flow - needs refactoring for proper isolation  
        pytest.skip("Complex connection deletion test - requires multi-user test isolation")

    async def test_user_report_creation_succeeds_when_valid_reason_provided(self, users_client, other_mock_user, bearer):
        """Should create user report successfully when valid reason is provided."""
        # Arrange
        target_user_id = other_mock_user["id"]
        report_data = {"reason": fake.sentence()}
        
        # Act
        response = await self.report_user(users_client, target_user_id, report_data, bearer)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.CREATED
        self.assert_resource_created(response_json)
        assert "Resource reported" in response_json["message"]

    async def test_user_report_creation_fails_when_reason_missing(self, users_client, other_mock_user, bearer):
        """Should return error when attempting to report user without providing reason."""
        # Arrange
        target_user_id = other_mock_user["id"]
        
        # Act & Assert
        await self.assert_missing_field_error(
            users_client, f"/users/{target_user_id}/report", {"reason": ""}, "reason", bearer
        )
