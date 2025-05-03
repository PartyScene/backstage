import pytest
from faker import Faker
from test_events_base import TestEventsBase
from http import HTTPStatus

fake = Faker()


@pytest.mark.asyncio(loop_scope="session")
class TestEventUpdates(TestEventsBase):
    async def test_update_event_details(self, event_client, mock_event, bearer):
        """Test updating an existing event's details."""
        # Ensure the mock event exists first (or create one if needed)
        # Assuming mock_event fixture provides a created event ID
        update_data = {"title": fake.catch_phrase(), "description": fake.text()}
        response = await self.update_event(
            event_client, mock_event["id"], update_data, bearer
        )
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "data" in response_json
        updated_event = response_json["data"]
        assert updated_event["title"] == update_data["title"]
        assert updated_event["description"] == update_data["description"]
        assert updated_event["id"] == mock_event["id"]  # Verify ID remains the same

    async def test_update_event_status(self, event_client, mock_event, bearer):
        """Test changing event status."""
        # Ensure the mock event exists first
        status_update = {"status": "cancelled"}

        response = await self.update_event_status(
            event_client, mock_event["id"], status_update, bearer
        )
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "data" in response_json
        updated_event = response_json["data"]
        assert updated_event["status"] == "cancelled"
        assert updated_event["id"] == mock_event["id"]

    async def test_update_nonexistent_event(self, event_client, bearer):
        """Test updating an event that does not exist."""
        non_existent_id = "nonexistentevent123"
        update_data = {"title": "This Should Fail"}
        response = await self.update_event(
            event_client, non_existent_id, update_data, bearer
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.NOT_FOUND.phrase
        assert "Event not found" in response_json["message"]

    async def test_update_event_status_invalid(self, event_client, mock_event, bearer):
        """Test updating event status with an invalid value."""
        status_update = {"status": "invalid_status_value"}

        response = await self.update_event_status(
            event_client, mock_event["id"], status_update, bearer
        )
        # Assuming the API validates status values
        assert response.status_code == HTTPStatus.BAD_REQUEST

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.BAD_REQUEST.phrase
        # Add assertion for specific error message if available

    async def test_update_event_unauthorized(
        self, event_client, mock_event, other_bearer
    ):
        """Test updating an event without proper authorization (e.g., not the host)."""
        # Assuming mock_event was created by 'bearer', and 'unauthorized_bearer' is different
        update_data = {"title": "Unauthorized Update Attempt"}
        response = await self.update_event(
            event_client, mock_event["id"], update_data, other_bearer
        )
        # Assuming the API checks ownership/permissions for updates
        assert (
            response.status_code == HTTPStatus.FORBIDDEN
        )  # Or UNAUTHORIZED depending on implementation

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.FORBIDDEN.phrase  # Or UNAUTHORIZED
        assert "Unauthorized" in response_json["message"]

    # Add more tests for partial updates, updating specific fields, etc.
