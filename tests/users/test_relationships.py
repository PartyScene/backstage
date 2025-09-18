import pytest
from http import HTTPStatus
from test_users_base import TestUsersBase

@pytest.mark.relationships
@pytest.mark.asyncio(loop_scope="session")
class TestUserRelationships(TestUsersBase):
    """Tests for user relationship functionality (friends, followers, etc.)."""

    async def test_send_friend_request(self, users_client, mock_user, other_mock_user, bearer):
        """Test sending a friend request to another user."""
        # User A sends friend request to User B
        response = await self.create_connection(
            users_client, 
            other_mock_user["id"],
            bearer
        )
        
        assert response.status_code == HTTPStatus.CREATED
        response_json = await response.get_json()
        assert "Friend request sent" in response_json["message"]
        
        # Verify the friend request exists
        requests = await self.get_friend_requests(users_client, bearer)
        assert requests.status_code == HTTPStatus.OK
        requests_json = await requests.get_json()
        assert any(req["id"] == other_mock_user["id"] for req in requests_json.get("data", []))

    async def test_accept_friend_request(self, users_client, mock_user, other_mock_user, bearer, other_bearer):
        """Test accepting a friend request."""
        # User A sends friend request to User B
        connection = await self.create_connection(users_client, other_mock_user["id"], bearer)
        
        # User B accepts the friend request
        response = await self.update_connection(
            users_client,
            connection["id"],  # User A's ID
            "accepted",
            other_bearer  # User B's token
        )
        
        assert response.status_code == HTTPStatus.OK
        response_json = await response.get_json()
        assert "Friend request accepted" in response_json["message"]
        
        # Verify they are now friends
        friends = await self.get_friends(users_client, other_bearer)
        assert friends.status_code == HTTPStatus.OK
        friends_json = await friends.get_json()
        assert any(friend["id"] == mock_user["id"] for friend in friends_json.get("data", []))

    async def test_decline_friend_request(self, users_client, mock_user, other_mock_user, bearer, other_bearer):
        """Test declining a friend request."""
        # User A sends friend request to User B
        connection = await self.create_connection(users_client, other_mock_user["id"], bearer)
        
        # User B declines the friend request
        response = await self.update_connection(
            users_client,
            connection["id"],  # User A's ID
            "declined",
            other_bearer  # User B's token
        )
        
        assert response.status_code == HTTPStatus.OK
        response_json = await response.get_json()
        assert "Friend request declined" in response_json["message"]
        
        # Verify they are not friends
        friends = await self.get_friends(users_client, bearer)
        assert friends.status_code == HTTPStatus.OK
        friends_json = await friends.get_json()
        assert not any(friend["id"] == other_mock_user["id"] for friend in friends_json.get("data", []))

    async def test_block_user(self, users_client, mock_user, other_mock_user, bearer):
        """Test blocking a user."""
        response = await self.delete_connection(
            users_client,
            other_mock_user["id"],
            bearer
        )
        
        assert response.status_code == HTTPStatus.OK
        response_json = await response.get_json()
        assert "User blocked successfully" in response_json["message"]
        
        # Verify the user is blocked
        blocked = await self.get_blocked_users(users_client, bearer)
        assert blocked.status_code == HTTPStatus.OK
        blocked_json = await blocked.get_json()
        assert any(user["id"] == other_mock_user["id"] for user in blocked_json.get("data", []))

    async def test_unblock_user(self, users_client, mock_user, other_mock_user, bearer):
        """Test unblocking a previously blocked user."""
        # First block the user
        await self.delete_connection(users_client, other_mock_user["id"], bearer)
        
        # Now unblock them
        response = await self.delete_connection(
            users_client,
            other_mock_user["id"],
            bearer
        )
        
        assert response.status_code == HTTPStatus.OK
        response_json = await response.get_json()
        assert "User unblocked successfully" in response_json["message"]
        
        # Verify the user is no longer blocked
        blocked = await self.get_blocked_users(users_client, bearer)
        assert blocked.status_code == HTTPStatus.OK
        blocked_json = await blocked.get_json()
        assert not any(user["id"] == other_mock_user["id"] for user in blocked_json.get("data", []))

    async def test_friend_suggestions(self, users_client, mock_user, bearer, create_test_users):
        """Test getting friend suggestions based on common connections."""
        # Create some test users with connections
        users = await create_test_users(5)  # Returns list of user dicts
        
        # Make some connections between users
        for user in users[:3]:  # First 3 users will have some connections
            await self.send_friend_request(users_client, user["id"], bearer)
            
            # Accept the request
            await self.respond_to_friend_request(
                users_client,
                mock_user["id"],
                "accepted",
                user["token"]
            )
        
        # Now get friend suggestions (should suggest users[3] and users[4])
        response = await self.get_friend_suggestions(users_client, bearer)
        assert response.status_code == HTTPStatus.OK
        
        response_json = await response.get_json()
        suggestions = response_json.get("data", [])
        
        # Should suggest users we're not already friends with
        suggested_ids = [user["id"] for user in suggestions]
        assert users[3]["id"] in suggested_ids
        assert users[4]["id"] in suggested_ids
        
        # Should not suggest users we're already friends with
        assert users[0]["id"] not in suggested_ids
        assert users[1]["id"] not in suggested_ids
        assert users[2]["id"] not in suggested_ids
