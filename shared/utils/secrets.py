from google.cloud import secretmanager_v1
import os


class SecretManager:

    KEK_SECRET_NAME = os.environ.get("KEK_SECRET_NAME")
    PROJECT_NUMBER = os.environ.get("PROJECT_NUMBER")

    def __init__(self):
        self._client = None

    async def _get_client(self):
        if not self._client:
            self._client = secretmanager_v1.SecretManagerServiceAsyncClient()
        return self._client

    async def get_kek_secret(self) -> bytes:
        client = await self._get_client()
        response = await client.access_secret_version(
            name=f"projects/{self.PROJECT_NUMBER}/secrets/{self.KEK_SECRET_NAME}/versions/latest"
        )
        return response.payload.data

    async def get_secret(self, secret_name: str) -> bytes:
        client = await self._get_client()
        response = await client.access_secret_version(
            name=f"projects/{self.PROJECT_NUMBER}/secrets/{secret_name}/versions/latest"
        )
        return response.payload.data
