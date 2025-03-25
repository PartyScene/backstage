import pytest
from faker import Faker
from httpx import AsyncClient
from test_r18e_base import TestR18EBase
from datetime import datetime
from quart.datastructures import FileStorage
import io

fake = Faker()


@pytest.mark.asyncio
class TestMLOperations(TestR18EBase):
    async def test_extract_features(
        self, r18e_client, bearer
    ):
        """Test extracting features."""
        files = {
            "file": FileStorage(
                io.BytesIO(b"fake image content"),
                filename="test_image.jpg",
                content_type="image/jpeg",
            )
        }
        
        response = await self.extract_features(r18e_client, files, bearer)
        assert response.status_code == 200
        features = await response.get_json()
        print(features)
        assert isinstance(features, dict)
        assert "id" in features