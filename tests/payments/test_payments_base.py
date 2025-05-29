import pytest_asyncio
import pytest
import urllib
from quart.testing import QuartClient


class TestPaymentsBase:
    async def create_payment_intent(self, client: QuartClient, event_id, ticket_count, bearer):
        """Helper method to create a payment intent"""
        return await client.post(
            f"/payments/{event_id}/create-intent",
            json={"ticket_count": ticket_count},
            headers={"Authorization": f"Bearer {bearer}"},
        )