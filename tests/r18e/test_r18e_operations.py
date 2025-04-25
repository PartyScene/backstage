import pytest
from faker import Faker
from httpx import AsyncClient
from test_r18e_base import TestR18EBase
from datetime import datetime
from quart.datastructures import FileStorage
import io

fake = Faker()


@pytest.mark.asyncio(loop_scope="session")
class TestMLOperations(TestR18EBase):
    
    async def test_recommended_events(self, r18e_client, mock_event, bearer):
        """Test event recommendation."""
        response = await self.recommend_events(r18e_client, mock_event['id'], bearer)
        assert response.status_code == 200
        events = await response.get_json()
        print(events)
        # assert "id" in events
    
    async def _test_extract_features(self, r18e_client, bearer):
        """Test extracting features."""
        files = {
            "file": FileStorage(
                self.generate_random_image(),
                filename=fake.file_name(category="image", extension="jpg"),
                content_type="image/jpeg",
            )
        }

        response = await self.extract_features(r18e_client, files, bearer)
        assert response.status_code == 200
        features = await response.get_json()
        print(features)
        # assert "id" in features
