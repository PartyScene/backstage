import pytest
from datetime import datetime, timedelta
from test_events_base import TestEventsBase
from http import HTTPStatus

@pytest.mark.pagination
@pytest.mark.asyncio(loop_scope="session")
class TestEventPaginationAndFiltering(TestEventsBase):
    """Tests for event pagination and filtering functionality."""

    @pytest.mark.parametrize("page,limit,expected_count", [
        (1, 5, 5),    # First page, 5 items
        (2, 5, 5),     # Second page, 5 items
        (3, 5, 0),     # Page beyond available data
        (1, 20, 10),   # All items in one page
    ])
    async def test_event_pagination(self, event_client, bearer, create_test_events, page, limit, expected_count):
        """Test pagination of event listings."""
        # Create test events if they don't exist
        if not hasattr(self, '_test_events_created'):
            await create_test_events(10)  # Create 10 test events
            self._test_events_created = True

        # Get paginated events
        response = await event_client.get(
            f"/events?page={page}&limit={limit}",
            headers={"Authorization": f"Bearer {bearer}"}
        )
        
        assert response.status_code == HTTPStatus.OK
        response_json = await response.get_json()
        events = response_json.get("data", [])
        
        assert len(events) == expected_count
        
        # Verify pagination metadata if implemented
        if "pagination" in response_json:
            pagination = response_json["pagination"]
            assert "total" in pagination
            assert "pages" in pagination
            assert "page" in pagination
            assert "limit" in pagination

    @pytest.mark.parametrize("status,expected_count", [
        ("upcoming", 4),
        ("past", 3),
        ("cancelled", 2),
        ("draft", 1),
    ])
    async def test_event_filter_by_status(self, event_client, bearer, create_test_events, status, expected_count):
        """Test filtering events by status."""
        # Create test events with different statuses if they don't exist
        if not hasattr(self, '_test_events_with_status_created'):
            # Create events with different statuses
            now = datetime.utcnow()
            events = [
                {"status": "upcoming", "start_time": (now + timedelta(days=1)).isoformat()},
                {"status": "upcoming", "start_time": (now + timedelta(days=2)).isoformat()},
                {"status": "upcoming", "start_time": (now + timedelta(days=3)).isoformat()},
                {"status": "upcoming", "start_time": (now + timedelta(days=4)).isoformat()},
                {"status": "past", "start_time": (now - timedelta(days=1)).isoformat()},
                {"status": "past", "start_time": (now - timedelta(days=2)).isoformat()},
                {"status": "past", "start_time": (now - timedelta(days=3)).isoformat()},
                {"status": "cancelled", "start_time": (now + timedelta(days=1)).isoformat()},
                {"status": "cancelled", "start_time": (now + timedelta(days=2)).isoformat()},
                {"status": "draft", "start_time": (now + timedelta(days=1)).isoformat()},
            ]
            
            for event in events:
                await create_test_events(1, **event)
            
            self._test_events_with_status_created = True

        # Filter events by status
        response = await event_client.get(
            f"/events?status={status}",
            headers={"Authorization": f"Bearer {bearer}"}
        )
        
        assert response.status_code == HTTPStatus.OK
        response_json = await response.get_json()
        events = response_json.get("data", [])
        
        assert len(events) == expected_count
        if events:  # If we expect and got events, verify the status matches
            assert all(event["status"] == status for event in events)

    @pytest.mark.parametrize("search_term,expected_matches", [
        ("conference", ["Tech Conference 2023", "Annual Developer Conference"]),
        ("workshop", ["Python Workshop", "Web Dev Workshop"]),
        ("2023", ["Tech Conference 2023", "Summer Party 2023"])
    ])
    async def test_event_search(self, event_client, bearer, create_test_events, search_term, expected_matches):
        """Test searching events by title."""
        # Create test events with different titles if they don't exist
        if not hasattr(self, '_test_search_events_created'):
            test_events = [
                {"title": "Tech Conference 2023"},
                {"title": "Python Workshop"},
                {"title": "Annual Developer Conference"},
                {"title": "Web Dev Workshop"},
                {"title": "Summer Party 2023"},
            ]
            
            for event in test_events:
                await create_test_events(1, **event)
            
            self._test_search_events_created = True

        # Search events
        response = await event_client.get(
            f"/events?search={search_term}",
            headers={"Authorization": f"Bearer {bearer}"}
        )
        
        assert response.status_code == HTTPStatus.OK
        response_json = await response.get_json()
        events = response_json.get("data", [])
        
        # Verify we got the expected number of matches
        assert len(events) == len(expected_matches)
        
        # Verify all expected matches are in the results
        result_titles = [event["title"] for event in events]
        for expected_title in expected_matches:
            assert expected_title in result_titles

    async def test_combined_filters(self, event_client, bearer, create_test_events):
        """Test combining multiple filters and pagination."""
        # Create test events with different attributes if they don't exist
        if not hasattr(self, '_test_combined_filter_events_created'):
            now = datetime.utcnow()
            test_events = [
                {"title": "Tech Meetup", "status": "upcoming", "start_time": (now + timedelta(days=1)).isoformat(), "category": "technology"},
                {"title": "Music Festival", "status": "upcoming", "start_time": (now + timedelta(days=2)).isoformat(), "category": "music"},
                {"title": "Coding Workshop", "status": "upcoming", "start_time": (now + timedelta(days=3)).isoformat(), "category": "technology"},
                {"title": "Art Exhibition", "status": "cancelled", "start_time": (now + timedelta(days=1)).isoformat(), "category": "art"},
                {"title": "Tech Conference", "status": "upcoming", "start_time": (now + timedelta(days=5)).isoformat(), "category": "technology"},
            ]
            
            for event in test_events:
                await create_test_events(1, **event)
            
            self._test_combined_filter_events_created = True

        # Apply multiple filters
        response = await event_client.get(
            "/events?status=upcoming&category=technology&search=tech&page=1&limit=2",
            headers={"Authorization": f"Bearer {bearer}"}
        )
        
        assert response.status_code == HTTPStatus.OK
        response_json = await response.get_json()
        events = response_json.get("data", [])
        
        # Should match "Tech Meetup" and "Tech Conference"
        assert len(events) == 2
        assert all(event["status"] == "upcoming" for event in events)
        assert all(event["category"] == "technology" for event in events)
        assert all("tech" in event["title"].lower() for event in events)
        
        # Verify pagination metadata if available
        if "pagination" in response_json:
            assert response_json["pagination"]["page"] == 1
            assert response_json["pagination"]["limit"] == 2
