import pytest_asyncio
import pytest
import urllib
from quart.testing import QuartClient

class TestEventsBase:
    async def create_event(self, client: QuartClient, event_data: dict, bearer):
        """Helper method to create an event"""
        return await client.post('/events', json=event_data, headers={"Authorization": f"Bearer {bearer}"})

    async def update_event(self, client: QuartClient, event_id: int, event_data: dict, bearer):
        """Helper method to update an event"""
        return await client.patch(f'/events/{event_id}', json=event_data, headers={"Authorization": f"Bearer {bearer}"})

    async def update_event_status(self, client: QuartClient, event_id: int, event_data: dict, bearer):
        """Helper method to update an event"""
        return await client.patch(f'/events/{event_id}/status', json=event_data, headers={"Authorization": f"Bearer {bearer}"})

    async def delete_event(self, client: QuartClient, event_id: int, bearer):
        """Helper method to delete an event"""
        return await client.delete(f'/events/{event_id}', headers={"Authorization": f"Bearer {bearer}"})

    async def get_events(self, client: QuartClient, bearer):
        """Helper method to get all events"""
        return await client.get(f'/events', headers={"Authorization": f"Bearer {bearer}"})

    async def get_event(self, client: QuartClient, event_id: int, bearer):
        """Helper method to get all events"""
        return await client.get(f'/events/{event_id}', headers={"Authorization": f"Bearer {bearer}"})
    
    async def get_events_distance(self, client: QuartClient, coordinates: list, bearer):
        """Helper method to get events within a distance"""
        params = urllib.parse.urlencode({"lat": coordinates[0], "lng": coordinates[1]})
        return await client.get(f'/events/distance?{params}', headers={"Authorization": f"Bearer {bearer}"})
