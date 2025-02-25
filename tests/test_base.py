import pytest_asyncio
import pytest
from quart.testing import QuartClient

class TestAuthBase:
    async def register_user(self, client: QuartClient, user_data: dict):
        """Helper method to register a user"""
        return await client.post('/register', json=user_data)
    
    async def login_user(self, client: QuartClient, credentials: dict):
        """Helper method to login a user"""
        return await client.post('/login', json=credentials)
    
    @pytest_asyncio.fixture(scope='module')
    async def get_token(self, client: QuartClient, user_data: dict):
        """Helper method to get auth token"""
        await self.register_user(client, user_data)
        response = await self.login_user(client, {
            'email': user_data['email'],
            'password': user_data['password']
        })
        data = await response.get_json()
        return data.get('access_token')