import pytest
import httpx
from http import HTTPStatus

@pytest.mark.asyncio
async def test_block_user(client: httpx.AsyncClient, auth_headers: dict, test_user: dict):
    """Test blocking a user"""
    # Create a second user to block
    target_user = await create_test_user(client, "target@example.com")
    
    # Block the user
    response = await client.post(
        f"/users/{target_user['id']}/block",
        headers=auth_headers
    )
    assert response.status_code == HTTPStatus.CREATED
    data = response.json()
    assert data["message"] == "User blocked successfully."
    assert "data" in data
    
    # Try to block again - should return the existing block
    response = await client.post(
        f"/users/{target_user['id']}/block",
        headers=auth_headers
    )
    assert response.status_code == HTTPStatus.CREATED
    assert response.json()["message"] == "User blocked successfully."

@pytest.mark.asyncio
async def test_block_self(client: httpx.AsyncClient, auth_headers: dict, test_user: dict):
    """Test that users cannot block themselves"""
    response = await client.post(
        f"/users/{test_user['id']}/block",
        headers=auth_headers
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["message"] == "Cannot block yourself."

@pytest.mark.asyncio
async def test_block_nonexistent_user(client: httpx.AsyncClient, auth_headers: dict):
    """Test blocking a user that doesn't exist"""
    response = await client.post(
        "/users/nonexistent123/block",
        headers=auth_headers
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["message"] == "User not found"

@pytest.mark.asyncio
async def test_unblock_user(client: httpx.AsyncClient, auth_headers: dict, test_user: dict):
    """Test unblocking a user"""
    # Create a second user to block/unblock
    target_user = await create_test_user(client, "target2@example.com")
    
    # First block the user
    response = await client.post(
        f"/users/{target_user['id']}/block",
        headers=auth_headers
    )
    assert response.status_code == HTTPStatus.CREATED
    
    # Now unblock the user
    response = await client.delete(
        f"/users/{target_user['id']}/block",
        headers=auth_headers
    )
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["message"] == "User unblocked successfully."
    assert "data" in data

@pytest.mark.asyncio
async def test_unblock_not_blocked_user(client: httpx.AsyncClient, auth_headers: dict):
    """Test unblocking a user that wasn't blocked"""
    # Create a user that we haven't blocked
    target_user = await create_test_user(client, "target3@example.com")
    
    # Try to unblock without blocking first
    response = await client.delete(
        f"/users/{target_user['id']}/block",
        headers=auth_headers
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["message"] == "Block relationship not found."

async def create_test_user(client: httpx.AsyncClient, email: str) -> dict:
    """Helper to create a test user"""
    # This is a simplified example - adjust based on your auth implementation
    response = await client.post("/auth/register", json={
        "email": email,
        "password": "TestPassword123!",
        "first_name": "Test",
        "last_name": "User"
    })
    return response.json()["data"]["user"]
