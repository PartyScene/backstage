import pytest
from faker import Faker
from quart.datastructures import FileStorage
from test_events_base import TestEventsBase
import io
from http import HTTPStatus

fake = Faker()


@pytest.mark.asyncio(loop_scope="session")
class TestEventCreation(TestEventsBase):
    async def test_create_valid_event(self, event_client, mock_event, bearer):
        """Test creating a valid event."""

        files = {
            "file": FileStorage(
                self.generate_random_image(),
                filename=fake.file_name(category="image", extension="jpg"),
                content_type="image/jpeg",
            )
        }

        response = await self.create_event(event_client, mock_event, files, bearer)
        assert response.status_code == HTTPStatus.CREATED

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.CREATED.phrase
        assert "data" in response_json
        created_event = response_json["data"]

        assert "id" in created_event
        mock_event["id"] = created_event[
            "id"
        ]  # Store ID for potential cleanup or subsequent tests

        assert created_event["host"] == mock_event["host"]
        # Add more assertions based on expected fields in created_event
        assert created_event["title"] == mock_event["title"]

    async def test_create_event_missing_fields(self, event_client, mock_event, bearer):
        """Test creating an event with missing required fields."""
        # Remove a required field, e.g., title
        invalid_event_data = mock_event.copy()
        invalid_event_data["id"] = "test_invalid"
        del invalid_event_data["title"]

        files = {
            "file": FileStorage(
                self.generate_random_image(),
                filename=fake.file_name(category="image", extension="jpg"),
                content_type="image/jpeg",
            )
        }

        response = await self.create_event(
            event_client, invalid_event_data, files, bearer
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.BAD_REQUEST.phrase
        assert "Missing required fields" in response_json["message"]

    async def test_create_event_no_files(self, event_client, mock_event, bearer):
        """Test creating an event without uploading files (if files are optional or handled differently)."""
        # Adapt this test based on whether files are strictly required
        test_data = mock_event.copy()
        test_data["id"] = "test_fileless"
        response = await self.create_event(
            event_client, test_data, {}, bearer
        )  # Pass empty dict for files

        # Assert based on expected behavior (e.g., success if files are optional, error if required)
        # Example: Assuming files are optional for creation via this test setup
        assert response.status_code == HTTPStatus.CREATED
        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.CREATED.phrase
        assert "data" in response_json
        created_event = response_json["data"]
        assert "id" in created_event
        assert not created_event.get(
            "filenames"
        )  # Check that filenames list is empty or absent

    # Add more tests for edge cases, invalid data types, etc.
