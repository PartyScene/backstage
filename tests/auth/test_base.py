import pytest_asyncio
import pytest
from quart.testing import QuartClient


class TestAuthBase:
    async def register_user(self, client: QuartClient, user_data: dict):
        """Helper method to register a user"""
        return await client.post("/auth/register", json=user_data)

    async def login_user(self, client: QuartClient, credentials: dict):
        """Helper method to login a user"""
        return await client.post("/auth/login", json=credentials)
