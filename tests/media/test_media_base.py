import pytest_asyncio
import pytest
import urllib
from quart.testing import QuartClient


class TestMediaBase:
    async def upload_media(self, client: QuartClient, files, metadata, bearer):
        """Helper method to upload media"""
        return await client.post(
            f"/upload",
            files=files,
            form=metadata,
            headers={"Authorization": f"Bearer {bearer}"},
        )

    # async def get_live_stream(self, client: QuartClient, livestream_id: int, bearer):
    #     """Helper method to get all events"""
    #     return await client.get(f'/{livestream_id}', headers={"Authorization": f"Bearer {bearer}"})
