"""
Shared Test Base Classes - Provides common TDD patterns for all microservices.
Follows Test-Driven Development best practices with AAA pattern and single responsibility.
"""
import pytest
import logging
from http import HTTPStatus
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from faker import Faker
import asyncio
import json

fake = Faker()
logger = logging.getLogger(__name__)


class BaseTestCase:
    """Base test case with common TDD utilities for all microservices."""

    # Common test data factories
    @pytest.fixture
    def valid_user_data(self):
        """Factory for valid user test data."""
        return {
            "user_id": fake.uuid4(),
            "email": fake.email(),
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "username": fake.user_name(),
            "password": "TestPass123!",
            "confirm_password": "TestPass123!"
        }

    @pytest.fixture
    def valid_event_data(self):
        """Factory for valid event test data."""
        return {
            "id": fake.uuid4(),
            "title": fake.catch_phrase(),
            "description": fake.text(max_nb_chars=200),
            "location": fake.address(),
            "price": fake.random_int(min=10, max=100),
            "host": "test_user",
            "time": (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z",
            "coordinates": [float(fake.longitude()), float(fake.latitude())],
            "categories": ["test", "integration"],
            "is_private": False,
            "is_free": False,
            "status": "scheduled"
        }

    @pytest.fixture  
    def valid_post_data(self):
        """Factory for valid post test data."""
        return {
            "content": fake.text(max_nb_chars=500),
            "type": "text"
        }

    # Common assertion helpers
    def assert_successful_response(self, response_json: Dict[str, Any], expected_status: HTTPStatus = HTTPStatus.OK):
        """Assert successful API response structure following TDD pattern."""
        assert "status" in response_json
        assert "message" in response_json
        assert "data" in response_json
        assert response_json["status"] == expected_status.phrase

    def assert_error_response(self, response_json: Dict[str, Any], expected_status: HTTPStatus, expected_message_contains: str = None):
        """Assert error API response structure following TDD pattern."""
        assert "status" in response_json
        assert "message" in response_json
        assert response_json["status"] == expected_status.phrase
        
        if expected_message_contains:
            assert expected_message_contains.lower() in response_json["message"].lower()

    def assert_auth_response(self, response_json: Dict[str, Any]):
        """Assert authentication response contains required tokens."""
        self.assert_successful_response(response_json)
        assert "access_token" in response_json["data"]
        assert "token_type" in response_json["data"]
        assert response_json["data"]["token_type"] == "bearer"

    def assert_resource_created(self, response_json: Dict[str, Any], resource_id_field: str = "id"):
        """Assert resource creation response."""
        self.assert_successful_response(response_json, HTTPStatus.CREATED)
        assert resource_id_field in response_json["data"]
        assert response_json["data"][resource_id_field] is not None

    def assert_pagination_structure(self, response_json: Dict[str, Any]):
        """Assert paginated response structure."""
        self.assert_successful_response(response_json)
        data = response_json["data"]
        assert "items" in data or "results" in data
        assert "total" in data or "count" in data
        assert "page" in data or "offset" in data

    # Common mock data helpers
    def create_mock_jwt_headers(self, token: str) -> Dict[str, str]:
        """Create authorization headers with JWT token."""
        return {"Authorization": f"Bearer {token}"}

    def create_mock_form_data(self, **fields) -> Dict[str, Any]:
        """Create mock form data for multipart requests."""
        form_data = {}
        for key, value in fields.items():
            if isinstance(value, list):
                for item in value:
                    form_data[f"{key}[]"] = item
            else:
                form_data[key] = value
        return form_data

    # Common HTTP operation helpers
    async def make_authenticated_request(self, client, method: str, endpoint: str, token: str, **kwargs):
        """Make authenticated HTTP request following AAA pattern."""
        headers = self.create_mock_jwt_headers(token)
        if 'headers' in kwargs:
            kwargs['headers'].update(headers)
        else:
            kwargs['headers'] = headers
            
        return await getattr(client, method.lower())(endpoint, **kwargs)

    async def assert_unauthorized_access(self, client, method: str, endpoint: str):
        """Assert endpoint requires authentication."""
        response = await getattr(client, method.lower())(endpoint)
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    async def assert_forbidden_access(self, client, method: str, endpoint: str, token: str):
        """Assert endpoint returns forbidden for current user."""
        response = await self.make_authenticated_request(client, method, endpoint, token)
        assert response.status_code == HTTPStatus.FORBIDDEN

    # Common test data validation
    def assert_valid_timestamp(self, timestamp_str: str):
        """Assert timestamp is valid ISO format."""
        try:
            datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except ValueError as e:
            pytest.fail(f"Invalid timestamp format: {timestamp_str} - {e}")

    def assert_valid_uuid(self, uuid_str: str):
        """Assert string is valid UUID."""
        import uuid
        try:
            uuid.UUID(uuid_str)
        except ValueError:
            pytest.fail(f"Invalid UUID: {uuid_str}")

    def assert_required_fields(self, data: Dict[str, Any], required_fields: List[str]):
        """Assert all required fields are present."""
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

    # Common async helpers
    async def wait_for_condition(self, condition_func, timeout: float = 5.0, interval: float = 0.1) -> bool:
        """Wait for async condition to become true."""
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            if await condition_func():
                return True
            await asyncio.sleep(interval)
        
        return False

    # Error simulation helpers
    def simulate_network_error(self):
        """Create mock network error for testing."""
        from unittest.mock import Mock
        error = Mock()
        error.side_effect = Exception("Network connection failed")
        return error

    def simulate_database_error(self):
        """Create mock database error for testing."""
        from unittest.mock import Mock
        error = Mock()
        error.side_effect = Exception("Database connection failed")
        return error


class AuthTestMixin:
    """Mixin for authentication-related test helpers."""

    async def register_user_successfully(self, client, user_data: Dict[str, Any]):
        """Register user and assert success - follows AAA pattern."""
        # Arrange - user_data provided
        
        # Act
        response = await client.post("/auth/register", json=user_data)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code in (HTTPStatus.CREATED, HTTPStatus.CONFLICT)
        return response, response_json

    async def login_user_successfully(self, client, credentials: Dict[str, Any]):
        """Login user and return token - follows AAA pattern."""
        # Arrange - credentials provided
        
        # Act
        response = await client.post("/auth/login", json=credentials)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        self.assert_auth_response(response_json)
        
        return response_json["data"]["access_token"]

    async def verify_otp_successfully(self, client, email: str, otp: str, context: str):
        """Verify OTP and assert success - follows AAA pattern."""
        # Arrange
        otp_data = {"email": email, "otp": otp, "context": context}
        
        # Act
        response = await client.post("/auth/verify", json=otp_data)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        return response, response_json


class CRUDTestMixin:
    """Mixin for CRUD operation test helpers."""

    async def create_resource_successfully(self, client, endpoint: str, data: Dict[str, Any], token: str, files: Dict = None):
        """Create resource and assert success - follows AAA pattern."""
        # Arrange
        request_kwargs = {"json": data} if not files else {"data": data, "files": files}
        
        # Act
        response = await self.make_authenticated_request(client, "POST", endpoint, token, **request_kwargs)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.CREATED
        self.assert_resource_created(response_json)
        
        return response_json["data"]

    async def get_resource_successfully(self, client, endpoint: str, token: str):
        """Get resource and assert success - follows AAA pattern."""
        # Act
        response = await self.make_authenticated_request(client, "GET", endpoint, token)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        self.assert_successful_response(response_json)
        
        return response_json["data"]

    async def update_resource_successfully(self, client, endpoint: str, data: Dict[str, Any], token: str):
        """Update resource and assert success - follows AAA pattern."""
        # Act
        response = await self.make_authenticated_request(client, "PUT", endpoint, token, json=data)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        self.assert_successful_response(response_json)
        
        return response_json["data"]

    async def delete_resource_successfully(self, client, endpoint: str, token: str):
        """Delete resource and assert success - follows AAA pattern."""
        # Act
        response = await self.make_authenticated_request(client, "DELETE", endpoint, token)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.OK
        self.assert_successful_response(response_json)
        
        return response_json


class ValidationTestMixin:
    """Mixin for validation test helpers."""

    async def assert_missing_field_error(self, client, endpoint: str, data: Dict[str, Any], missing_field: str, token: str = None):
        """Assert API returns error when required field is missing."""
        # Arrange
        test_data = data.copy()
        del test_data[missing_field]
        
        # Act
        if token:
            response = await self.make_authenticated_request(client, "POST", endpoint, token, json=test_data)
        else:
            response = await client.post(endpoint, json=test_data)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code == HTTPStatus.BAD_REQUEST
        self.assert_error_response(response_json, HTTPStatus.BAD_REQUEST, missing_field)

    async def assert_invalid_data_error(self, client, endpoint: str, invalid_data: Dict[str, Any], token: str = None):
        """Assert API returns error for invalid data."""
        # Act
        if token:
            response = await self.make_authenticated_request(client, "POST", endpoint, token, json=invalid_data)
        else:
            response = await client.post(endpoint, json=invalid_data)
        response_json = await response.get_json()
        
        # Assert
        assert response.status_code in (HTTPStatus.BAD_REQUEST, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assert_error_response(response_json, response.status_code)


# Combined base class for all microservice tests
class StreamlinedTestBase(BaseTestCase, AuthTestMixin, CRUDTestMixin, ValidationTestMixin):
    """
    Comprehensive base class combining all TDD patterns for streamlined testing.
    All microservice test classes should inherit from this.
    """
    pass
