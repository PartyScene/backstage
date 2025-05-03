import pytest
from datetime import datetime, timedelta
from faker import Faker
from test_events_base import TestEventsBase
from http import HTTPStatus
from urllib.parse import urlencode

faker = Faker()


@pytest.mark.asyncio(loop_scope="session")
class TestEventQueries(TestEventsBase):
    async def test_list_events(self, event_client, bearer):
        """Test retrieving a list of events."""
        response = await self.get_events(event_client, bearer)
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "data" in response_json
        events = response_json["data"]
        assert isinstance(events, list)
        # Optionally check if the list is not empty if events are expected
        # assert len(events) > 0

    async def test_get_event(self, event_client, mock_event, bearer):
        """Test retrieving a specific event by ID."""
        # Ensure mock_event has an ID (created in a fixture or previous test)
        assert "id" in mock_event, "Mock event must have an ID for this test"
        response = await self.get_event(event_client, mock_event["id"], bearer)
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "data" in response_json
        event = response_json["data"]
        assert isinstance(event, dict)
        assert event["id"] == mock_event["id"]
        assert event["title"] == mock_event["title"]  # Check other fields

    async def test_get_nonexistent_event(self, event_client, bearer):
        """Test retrieving an event that does not exist."""
        non_existent_id = "nonexistentevent123"
        response = await self.get_event(event_client, non_existent_id, bearer)
        assert response.status_code == HTTPStatus.NOT_FOUND

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.NOT_FOUND.phrase
        assert "Event not found" in response_json["message"]

    # async def test_filter_events_by_date(self, client):
    #     """Test filtering events by date range."""
    #     start_date = datetime.now().isoformat()
    #     end_date = (datetime.now() + timedelta(days=30)).isoformat()

    #     response = await client.get(f"/events/location?start_date={start_date}&end_date={end_date}")
    #     assert response.status_code == 200

    #     filtered_events = await response.get_json()
    #     for event in filtered_events:
    #         event_start = datetime.fromisoformat(event['start_time'])
    #         assert start_date <= event_start.isoformat() <= end_date

    async def test_filter_events_by_location(self, event_client, bearer):
        """Test filtering events by distance from N meters."""
        # Use a known location or generate one
        lat, lng = faker.latitude(), faker.longitude()
        distance = 5000  # 5km

        response = await self.get_events_distance(
            event_client, [lat, lng], distance, bearer
        )
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "data" in response_json
        filtered_events = response_json["data"]
        assert isinstance(filtered_events, list)
        # Further assertions could involve checking distances if possible/needed

    async def test_filter_events_by_location_invalid_params(self, event_client, bearer):
        """Test filtering events by distance with invalid parameters."""
        params = urlencode({"lat": "invalid", "lng": "invalid"})
        response = await event_client.get(
            f"/events?{params}", headers={"Authorization": f"Bearer {bearer}"}
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.BAD_REQUEST.phrase
        # Add assertion for specific error message if available

    async def test_list_private_events(self, event_client, bearer):
        """Test retrieving a list of private events."""
        # Note: This test assumes the underlying DB method correctly filters.
        # More robust testing might involve creating specific private/public events.
        response = await self.get_private_events(event_client, bearer)
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "data" in response_json
        events = response_json["data"]
        assert isinstance(events, list)
        # Optionally, verify if events returned are indeed private if possible

    async def test_list_public_events(self, event_client):
        """Test retrieving a list of public events."""
        # Note: Similar to private events, relies on DB filtering.
        response = await self.get_public_events(event_client)
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "data" in response_json
        events = response_json["data"]
        assert isinstance(events, list)
        # Optionally, verify if events returned are indeed public if possible

    async def test_report_event(self, event_client, mock_event, bearer):
        """Test reporting an existing event."""
        assert "id" in mock_event, "Mock event must have an ID for this test"
        report_data = {"reason": faker.sentence()}

        response = await self.report_event(
            event_client, mock_event["id"], report_data, bearer
        )
        assert response.status_code == HTTPStatus.CREATED

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.CREATED.phrase
        assert "Resource reported" in response_json["message"]
        assert "data" in response_json
        assert "id" in response_json["data"]  # Check if report ID is returned

    async def test_report_event_missing_reason(self, event_client, mock_event, bearer):
        """Test reporting an event without providing a reason."""
        assert "id" in mock_event, "Mock event must have an ID for this test"
        report_data = {}  # Missing reason
        response = await self.report_event(
            event_client, mock_event["id"], report_data, bearer
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_json = await response.get_json()
        assert "Reason is required" in response_json["message"]

    # async def test_buy_ticket(self, event_client, mock_event, bearer):
    #     """Test buying a ticket for an event."""
    #     assert "id" in mock_event, "Mock event must have an ID for this test"
    #     response = await self.buy_ticket(event_client, mock_event["id"], bearer)
    #     assert response.status_code == HTTPStatus.CREATED
    #     response_json = await response.get_json()
    #     assert "Ticket purchased successfully" in response_json["message"]

    # Add tests for pagination (limit, page parameters) if implemented
    # Add tests for other filtering options (private, categories, etc.)
