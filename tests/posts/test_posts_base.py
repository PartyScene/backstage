import pytest_asyncio
import pytest
import urllib
from quart.testing import QuartClient


class TestPostsBase:
    async def create_post(self, client: QuartClient, files, metadata, bearer):
        """Helper method to upload media"""
        return await client.post(
            f"/posts",
            files=files,
            form=metadata,
            headers={"Authorization": f"Bearer {bearer}"},
        )

    async def create_comment(self, client: QuartClient, post_id, data, bearer):
        """Helper method to create a comment"""
        return await client.post(
            f"/posts/{post_id}/comments",
            json=data,
            headers={"Authorization": f"Bearer {bearer}"},
        )

    async def fetch_comments(self, client: QuartClient, post_id, bearer):
        """Helper method to get comments for a post"""
        return await client.get(
            f"/posts/{post_id}/comments", headers={"Authorization": f"Bearer {bearer}"}
        )

    async def delete_comment(self, client: QuartClient, post_id, comment_id, bearer):
        """Helper method to delete a comment"""
        return await client.delete(
            f"/posts/{post_id}/comments/{comment_id}",
            headers={"Authorization": f"Bearer {bearer}"},
        )

    async def fetch_event_posts(self, client: QuartClient, event_id, bearer):
        """Helper method to get all events"""
        return await client.get(
            f"/posts/event/{event_id}", headers={"Authorization": f"Bearer {bearer}"}
        )

    async def fetch_post(self, client: QuartClient, post_id, bearer):
        """Helper method to get a post."""
        return await client.get(
            f"/posts/{post_id}", headers={"Authorization": f"Bearer {bearer}"}
        )

    async def delete_post(self, client: QuartClient, post_id, bearer):
        """Helper method to delete a post."""
        return await client.delete(
            f"/posts/{post_id}", headers={"Authorization": f"Bearer {bearer}"}
        )
