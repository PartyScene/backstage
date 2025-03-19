import pytest
from faker import Faker
from httpx import AsyncClient
from datetime import datetime
import io
import os
from PIL import Image
from quart.datastructures import FileStorage
from test_media_base import TestMediaBase

fake = Faker()


@pytest.mark.asyncio
class TestMediaOperations(TestMediaBase):
    def generate_random_image(self, color):
        image = Image.new("RGB", (100, 100), color=color)
        # image.tobytes()
        img_bytes = io.BytesIO()
        image.save(img_bytes, format="JPEG")
        return img_bytes

    async def test_upload_image(self, media_client, mock_event, bearer):
        """Test uploading an image file."""
        # Create a mock image file
        color = fake.color_rgb()
        files = {
            "file": FileStorage(
                self.generate_random_image(color),
                filename=mock_event["id"]
                + "/"
                + str(color)
                + "/"
                + fake.file_name(category="image"),
                content_type="image/jpeg",
            )
        }
        metadata = {
            "title": fake.sentence(),
            "description": fake.text(max_nb_chars=200),
            "event": mock_event["id"],
            "type": "image",
        }

        response = await self.upload_media(media_client, files, metadata, bearer)
        assert response.status_code == 201
        uploaded_file = await response.get_json()

        assert "creator" in uploaded_file
        assert "url" in uploaded_file

    # async def test_get_media_info(self, async_client, test_config):
    #     """Test retrieving media file information."""
    #     # First upload a file
    #     files = {
    #         'file': ('test.txt', io.BytesIO(b'test content'), 'text/plain')
    #     }
    #     upload_response = await async_client.post("/media/upload", files=files)
    #     file_id = upload_response.json()['file_id']

    #     # Get file info
    #     response = await async_client.get(f"/media/{file_id}/info")
    #     assert response.status_code == 200
    #     file_info = response.json()

    #     assert file_info['file_id'] == file_id
    #     assert 'filename' in file_info
    #     assert 'mime_type' in file_info
    #     assert 'size' in file_info

    # async def test_delete_media(self, async_client):
    #     """Test deleting a media file."""
    #     # First upload a file
    #     files = {
    #         'file': ('test.txt', io.BytesIO(b'test content'), 'text/plain')
    #     }
    #     upload_response = await async_client.post("/media/upload", files=files)
    #     file_id = upload_response.json()['file_id']

    #     # Delete the file
    #     response = await async_client.delete(f"/media/{file_id}")
    #     assert response.status_code == 204

    #     # Verify file is deleted
    #     get_response = await async_client.get(f"/media/{file_id}/info")
    #     assert get_response.status_code == 404

    # @pytest.mark.parametrize("invalid_file", [
    #     ('test.exe', b'invalid content', 'application/x-msdownload'),  # Invalid file type
    #     ('test.jpg', b'', 'image/jpeg'),  # Empty file
    #     ('test.jpg', b'x' * (10 * 1024 * 1024 + 1), 'image/jpeg')  # File too large
    # ])
    # async def test_upload_invalid_file(self, async_client, invalid_file):
    #     """Test uploading invalid files."""
    #     filename, content, mime_type = invalid_file
    #     files = {
    #         'file': (filename, io.BytesIO(content), mime_type)
    #     }

    #     response = await async_client.post("/media/upload", files=files)
    #     assert response.status_code == 400

    # async def test_update_media_metadata(self, async_client):
    #     """Test updating media metadata."""
    #     # First upload a file
    #     files = {
    #         'file': ('test.jpg', io.BytesIO(b'test content'), 'image/jpeg')
    #     }
    #     upload_response = await async_client.post("/media/upload", files=files)
    #     file_id = upload_response.json()['file_id']

    #     # Update metadata
    #     update_data = {
    #         'title': fake.sentence(),
    #         'description': fake.text(max_nb_chars=200),
    #         'tags': [fake.word() for _ in range(3)]
    #     }

    #     response = await async_client.put(
    #         f"/media/{file_id}/metadata",
    #         json=update_data
    #     )
    #     assert response.status_code == 200
    #     updated_file = response.json()

    #     assert updated_file['metadata']['title'] == update_data['title']
    #     assert updated_file['metadata']['description'] == update_data['description']

    # @pytest.mark.performance
    # def test_media_retrieval_performance(self, benchmark, async_client):
    #     """Benchmark media file retrieval performance."""
    #     # First upload a file
    #     files = {
    #         'file': ('test.jpg', io.BytesIO(b'test content'), 'image/jpeg')
    #     }
    #     upload_response = async_client.post("/media/upload", files=files)
    #     file_id = upload_response.json()['file_id']

    #     result = benchmark(async_client.get, f"/media/{file_id}/info")
    #     assert result.status_code == 200
