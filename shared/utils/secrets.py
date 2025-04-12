from google.cloud import secretmanager_v1
import os


class SecretManager:

    secret_manager = secretmanager_v1.SecretManagerServiceAsyncClient()
    KEK_SECRET_NAME = os.environ.get("KEK_SECRET_NAME")
    PROJECT_NUMBER = os.environ.get("PROJECT_NUMBER")

    async def get_kek_secret(self) -> bytes:
        response = await self.secret_manager.access_secret_version(
            name=f"projects/{self.PROJECT_NUMBER}/secrets/{self.KEK_SECRET_NAME}/versions/latest"
        )
        return response.payload.data

    async def get_secret(self, secret_name: str) -> bytes:
        response = await self.secret_manager.access_secret_version(
            name=f"projects/{self.PROJECT_NUMBER}/secrets/{secret_name}/versions/latest"
        )
        return response.payload.data
