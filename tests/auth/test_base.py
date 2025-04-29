import pytest_asyncio
import urllib
import pytest
from quart.testing import QuartClient


class TestAuthBase:
    async def register_user(self, client: QuartClient, user_data: dict):
        """Helper method to register a user"""
        return await client.post("/auth/register", json=user_data)

    async def verify_otp(self, client: QuartClient, user_data: dict):
        return await client.post(
            "/auth/verify", json={"email": user_data["email"], "otp": user_data["otp"]}
        )

    async def login_user(self, client: QuartClient, credentials: dict):
        """Helper method to login a user"""
        return await client.post("/auth/login", json=credentials)

    async def health_check(self, client: QuartClient):
        """Helper method to check service health"""
        return await client.get("/auth/health")

    async def lead_generation(self, client: QuartClient, data):
        """Helper method to generate a lead"""
        return await client.post("/leads", json=data)

    async def check_username_exists(self, client: QuartClient, user_data):
        """Helper method to recommend events"""
        params = urllib.parse.urlencode(
            {"type": "username", "param": user_data["username"]}
        )

        return await client.get(f"/auth/exists?{params}")

    async def check_email_exists(self, client: QuartClient, user_data):
        """Helper method to recommend events"""
        params = urllib.parse.urlencode({"type": "email", "param": user_data["email"]})

        return await client.get(f"/auth/exists?{params}")
