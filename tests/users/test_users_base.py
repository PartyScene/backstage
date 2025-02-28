import pytest_asyncio
import pytest
import urllib
from quart.testing import QuartClient

class TestUsersBase:

    async def get_user(self, client: QuartClient, user_id, bearer):
        """Helper method to get a user"""
        return await client.get(f'/users/{event_id}', headers={"Authorization": f"Bearer {bearer}"})
    
    async def create_connection(self, client: QuartClient, post_id, bearer):
        """Helper method to get a post."""
        return await client.get(f'/{post_id}', headers={"Authorization": f"Bearer {bearer}"})
        
    async def delete_connection(self, client: QuartClient, post_id, bearer):
        """Helper method to get a post."""
        return await client.get(f'/{post_id}', headers={"Authorization": f"Bearer {bearer}"})
    
    async def update_connection(self, client: QuartClient, post_id, bearer):
        """Helper method to get a post."""
        return await client.get(f'/{post_id}', headers={"Authorization": f"Bearer {bearer}"})
    
    async def update_user(self, client: QuartClient, user_id, metadata, earer):
        """Helper method to update a user."""
        return await client.patch(f'/users/{user_id}', json=metadata, headers={"Authorization": f"Bearer {bearer}"})
    
    async def delete_user(self, client: QuartClient, post_id, bearer):
        """Helper method to delete a post."""
        return await client.delete(f'/{post_id}', headers={"Authorization": f"Bearer {bearer}"})