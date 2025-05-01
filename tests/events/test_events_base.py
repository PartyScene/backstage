import pytest_asyncio
import pytest
import urllib
from quart.testing import QuartClient
from PIL import Image
import io
from typing import IO


class TestEventsBase:
    def generate_random_image(self, color="blue") -> IO[bytes]:
        image = Image.new("RGB", (100, 100), color=color)
        # image.tobytes()
        img_bytes = io.BytesIO()
        image.save(img_bytes, format="JPEG")
        img_bytes.seek(0)
        return img_bytes

    async def create_event(self, client: QuartClient, event_data: dict, files, bearer):
        """Helper method to create an event"""
        return await client.post(
            "/events",
            form=event_data,
            files=files,
            headers={"Authorization": f"Bearer {bearer}"},
        )

    async def update_event(
        self, client: QuartClient, event_id, event_data: dict, bearer
    ):
        """Helper method to update an event"""
        return await client.patch(
            f"/events/{event_id}",
            json=event_data,
            headers={"Authorization": f"Bearer {bearer}"},
        )

    async def update_event_status(
        self, client: QuartClient, event_id, event_data: dict, bearer
    ):
        """Helper method to update an event"""
        return await client.patch(
            f"/events/{event_id}/status",
            json=event_data,
            headers={"Authorization": f"Bearer {bearer}"},
        )

    async def delete_event(self, client: QuartClient, event_id, bearer):
        """Helper method to delete an event"""
        return await client.delete(
            f"/events/{event_id}", headers={"Authorization": f"Bearer {bearer}"}
        )

    async def get_events(self, client: QuartClient, bearer):
        """Helper method to get all events"""
        return await client.get(
            f"/events", headers={"Authorization": f"Bearer {bearer}"}
        )

    async def get_event(self, client: QuartClient, event_id, bearer):
        """Helper method to get all events"""
        return await client.get(
            f"/events/{event_id}", headers={"Authorization": f"Bearer {bearer}"}
        )

    async def get_events_distance(self, client: QuartClient, coordinates: list, distance, bearer):
        """Helper method to get events within a distance"""
        params = urllib.parse.urlencode({"lat": coordinates[0], "lng": coordinates[1], "distance": distance})
        return await client.get(
            f"/events?{params}", headers={"Authorization": f"Bearer {bearer}"}
        )
