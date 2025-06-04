import pytest_asyncio
import pytest
import urllib
from quart.testing import QuartClient


class TestUsersBase:

    async def get_user(self, client: QuartClient, user_id, bearer):
        """Helper method to get a user"""
        return await client.get(
            f"/users/{user_id}", headers={"Authorization": f"Bearer {bearer}"}
        )
    async def get_user_events(self, client: QuartClient, bearer):
        """Helper method to get events related to the current user."""
        return await client.get(f"/user/events", headers={"Authorization": f"Bearer {bearer}"})
    
    async def get_me(self, client: QuartClient, bearer):
        """Helper method to get a user"""
        return await client.get(f"/user", headers={"Authorization": f"Bearer {bearer}"})

    async def create_connection(self, client: QuartClient, target_id, bearer):
        """Helper method to create a connection."""
        return await client.post(
            f"/friends",
            json={"target_id": target_id},
            headers={"Authorization": f"Bearer {bearer}"},
        )

    async def fetch_connections(self, client: QuartClient, bearer):
        """Helper method to fetch connections."""
        return await client.get(
            f"/friends",
            headers={"Authorization": f"Bearer {bearer}"},
        )

    async def delete_connection(self, client: QuartClient, connection_id, bearer):
        """Helper method to delete a connection."""
        return await client.delete(
            f"/friends/{connection_id}", headers={"Authorization": f"Bearer {bearer}"}
        )

    async def update_connection(
        self, client: QuartClient, connection_id, connection_status, bearer
    ):
        """Helper method to edit a connection."""
        return await client.patch(
            f"/friends/{connection_id}",
            json={"status": connection_status},
            headers={"Authorization": f"Bearer {bearer}"},
        )

    async def update_user(self, client: QuartClient, metadata, bearer):
        """Helper method to update current user."""
        return await client.patch(
            "/user", json=metadata, headers={"Authorization": f"Bearer {bearer}"}
        )

    async def delete_user(self, client: QuartClient, user_id, bearer):
        """Helper method to delete a user."""
        return await client.delete(
            f"/users/{user_id}", headers={"Authorization": f"Bearer {bearer}"}
        )

    async def report_user(self, client: QuartClient, user_id, report_data, bearer):
        """Helper method to report a user"""
        return await client.post(
            f"/users/{user_id}/report",
            json=report_data,
            headers={"Authorization": f"Bearer {bearer}"},
        )
