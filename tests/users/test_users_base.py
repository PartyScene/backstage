import pytest_asyncio
import pytest
import urllib
from quart.testing import QuartClient

class TestUsersBase:

    async def get_user(self, client: QuartClient, user_id, bearer):
        """Helper method to get a user"""
        return await client.get(f'/users/{user_id}', headers={"Authorization": f"Bearer {bearer}"})
    
    async def create_connection(self, client: QuartClient, post_id, bearer):
        """Helper method to create a connection."""
        return await client.get(f'/{post_id}', headers={"Authorization": f"Bearer {bearer}"})
        
    async def delete_connection(self, client: QuartClient, post_id, bearer):
        """Helper method to delete a connection."""
        return await client.get(f'/{post_id}', headers={"Authorization": f"Bearer {bearer}"})
    
    async def update_connection(self, client: QuartClient, post_id, bearer):
        """Helper method to set connection."""
        return await client.get(f'/{post_id}', headers={"Authorization": f"Bearer {bearer}"})
    
    async def update_user(self, client: QuartClient, metadata, bearer):
        """Helper method to update current user."""
        return await client.patch('/user', json=metadata, headers={"Authorization": f"Bearer {bearer}"})
    
    async def delete_user(self, client: QuartClient, user_id, bearer):
        """Helper method to delete a user."""
        return await client.delete('/users/{user_id}', headers={"Authorization": f"Bearer {bearer}"})