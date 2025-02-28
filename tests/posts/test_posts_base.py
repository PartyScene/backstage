import pytest_asyncio
import pytest
import urllib
from quart.testing import QuartClient

class TestPostsBase:
    async def create_post(self, client: QuartClient, files, metadata, bearer):
        """Helper method to upload media"""
        return await client.post(f'/', files=files, json=metadata, headers={"Authorization": f"Bearer {bearer}"})

    async def fetch_event_posts(self, client: QuartClient, event_id, bearer):
        """Helper method to get all events"""
        return await client.get(f'/event/{event_id}', headers={"Authorization": f"Bearer {bearer}"})
    
    async def fetch_post(self, client: QuartClient, post_id, bearer):
        """Helper method to get a post."""
        return await client.get(f'/{post_id}', headers={"Authorization": f"Bearer {bearer}"})

    async def delete_post(self, client: QuartClient, post_id, bearer):
        """Helper method to delete a post."""
        return await client.delete(f'/{post_id}', headers={"Authorization": f"Bearer {bearer}"})