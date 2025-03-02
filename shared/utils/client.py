from typing import Dict, Any
import httpx
from quart.datastructures import FileStorage
from quart import Request


class MediaClient:
    def __init__(self, media_service_url: str) -> None:
        self.media_service_url = media_service_url.rstrip("/")

    async def upload_media(self, request: Request, file: FileStorage) -> Dict[str, Any]:
        """
        Upload media file to the media microservice

        Args:
            request: The Quart request object
            file: FileStorage object containing the file to upload

        Returns:
            Dict containing the response from media service, including the URL of uploaded file
        """
        async with httpx.AsyncClient() as client:

            # Combine files and form data
            files = {"file": (file.filename, file.stream, file.content_type)}

            response = await client.post(
                f"{self.media_service_url}/upload",
                headers=request.headers,
                files=files,
                data=dict(await request.form),
            )
            response.raise_for_status()
            return response.json()


