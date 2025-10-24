import pytest
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_users_base import TestUsersBase
from http import HTTPStatus


@pytest.mark.asyncio(loop_scope="session")
class TestUserBlocking(TestUsersBase):
    """Streamlined user blocking tests following TDD best practices."""

    async def test_user_blocking_succeeds_when_target_user_exists(self, users_client, other_mock_user, bearer):
        """Should block user successfully when target user exists."""
        # Arrange
        target_user_id = other_mock_user["id"]
        
        # Act
        response = await self.block_user(users_client, target_user_id, bearer)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.CREATED
        self.assert_resource_created(response_json)
        assert "User blocked successfully." in response_json["message"]

    async def test_user_blocking_fails_when_attempting_to_block_self(self, users_client, mock_user, bearer):
        """Should return error when user attempts to block themselves."""
        # Arrange
        own_user_id = mock_user["id"]
        
        # Act
        response = await self.block_user(users_client, own_user_id, bearer)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.BAD_REQUEST
        self.assert_error_response(response_json, HTTPStatus.BAD_REQUEST, "Cannot block yourself")

    async def test_user_blocking_fails_when_target_user_not_found(self, users_client, bearer):
        """Should return not found when attempting to block non-existent user."""
        # Arrange
        nonexistent_user_id = "nonexistent123"
        
        # Act
        response = await self.block_user(users_client, nonexistent_user_id, bearer)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.NOT_FOUND
        self.assert_error_response(response_json, HTTPStatus.NOT_FOUND, "User not found")

    async def test_user_unblocking_succeeds_when_user_is_blocked(self, users_client, other_mock_user, bearer):
        """Should unblock user successfully when user is currently blocked."""
        # Arrange - Block user first
        target_user_id = other_mock_user["id"]
        block_response = await self.block_user(users_client, target_user_id, bearer)
        assert block_response.status_code == HTTPStatus.CREATED
        
        # Act
        response = await self.unblock_user(users_client, target_user_id, bearer)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        self.assert_successful_response(response_json)
        assert "User unblocked successfully." in response_json["message"]

    async def test_user_unblocking_fails_when_user_not_blocked(self, users_client, other_mock_user, bearer):
        """Should return not found when attempting to unblock user that isn't blocked."""
        # Arrange
        target_user_id = other_mock_user["id"]
        
        # Act
        response = await self.unblock_user(users_client, target_user_id, bearer)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.NOT_FOUND
        self.assert_error_response(response_json, HTTPStatus.NOT_FOUND, "Block relationship not found")

    async def test_blocked_users_list_retrieval_succeeds_when_authenticated(self, users_client, bearer):
        """Should retrieve blocked users list successfully when authenticated."""
        # Act
        response = await self.get_blocked_users(users_client, bearer)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        self.assert_successful_response(response_json)
        assert isinstance(response_json["data"], list)
