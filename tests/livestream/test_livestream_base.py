import pytest_asyncio
import pytest
import urllib
from quart.testing import QuartClient

class TestLiveStreamBase:
    async def create_live_stream(self, client: QuartClient, stream_event_id: str, bearer):
        """Helper method to create a live stream"""
        return await client.post(f'/{stream_event_id}', headers={"Authorization": f"Bearer {bearer}"})

    async def get_live_stream(self, client: QuartClient, livestream_id: int, bearer):
        """Helper method to get a live stream"""
        return await client.get(f'/{livestream_id}', headers={"Authorization": f"Bearer {bearer}"})