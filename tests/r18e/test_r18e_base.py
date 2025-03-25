import pytest_asyncio
import pytest
import urllib
import io

from quart.testing import QuartClient
from typing import IO
from PIL import Image

class TestR18EBase:
    def generate_random_image(self, color = "blue") -> IO[bytes]:
        image = Image.new("RGB", (100, 100), color=color)
        # image.tobytes()
        img_bytes = io.BytesIO()
        image.save(img_bytes, format="JPEG")
        img_bytes.seek(0)
        return img_bytes

    async def extract_features(self, client: QuartClient, files, bearer):
        """Helper method to extract features"""
        return await client.post(
            f"/r18e/features/extract",
            files=files,
            query_string={"event": "test"},
            headers={"Authorization": f"Bearer {bearer}"},
        )

    # async def create_comment(self, client: QuartClient, post_id, data, bearer):
    #     """Helper method to create a comment"""
    #     return await client.post(
    #         f"/posts/{post_id}/comments",
    #         json=data,
    #         headers={"Authorization": f"Bearer {bearer}"},
    #     )

    # async def get_comments(self, client: QuartClient, post_id, bearer):
    #     """Helper method to get comments for a post"""
    #     return await client.get(
    #         f"/posts/{post_id}/comments", headers={"Authorization": f"Bearer {bearer}"}
    #     )

    # async def delete_comment(self, client: QuartClient, post_id, comment_id, bearer):
    #     """Helper method to delete a comment"""
    #     return await client.delete(
    #         f"/posts/{post_id}/comments/{comment_id}",
    #         headers={"Authorization": f"Bearer {bearer}"},
    #     )

    # async def fetch_event_posts(self, client: QuartClient, event_id, bearer):
    #     """Helper method to get all events"""
    #     return await client.get(
    #         f"/posts/event/{event_id}", headers={"Authorization": f"Bearer {bearer}"}
    #     )

    # async def fetch_post(self, client: QuartClient, post_id, bearer):
    #     """Helper method to get a post."""
    #     return await client.get(
    #         f"/posts/{post_id}", headers={"Authorization": f"Bearer {bearer}"}
    #     )

    # async def delete_post(self, client: QuartClient, post_id, bearer):
    #     """Helper method to delete a post."""
    #     return await client.delete(
    #         f"/posts/{post_id}", headers={"Authorization": f"Bearer {bearer}"}
    #     )
