import os
import pprint
import sys


# Add project root and shared directories to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shared")
)

import pytest
import pytest_asyncio
from faker import Faker
import asyncio
import logging
import httpx
from datetime import datetime, timedelta
import io
from unittest.mock import MagicMock
import uvloop
from surrealdb import AsyncSurreal

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global Faker instance for generating test data
fake = Faker()


# the custom event_loop fixture and update the async fixtures
# @pytest.fixture(scope="session", autouse=True)
# def event_loop():
#     uvloop.install()
#     loop = asyncio.new_event_loop()
#     yield loop
#     loop.close()


# @pytest_asyncio.fixture(scope="session", loop_scope="session")
# async def surreal():
#     """Create a session-scoped database connection"""
#     logger.debug(os.environ)
#     db = AsyncSurreal(os.environ["SURREAL_URI"])
#     await db.connect(os.environ["SURREAL_URI"])
#     await db.signin(
#         {"username": os.environ["SURREAL_USER"], "password": os.environ["SURREAL_PASS"]}
#     )
#     await db.use("partyscene", "partyscene")
#     yield db
#     await db.close()

from redis.asyncio import Redis


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def redis_connection():
    """Fixture to set up Redis connection for testing."""
    redis_uri = os.getenv(
        "REDIS_URI", "redis://localhost:6379"
    )  # Set the URI if not already set
    redis = Redis.from_url(redis_uri, decode_responses=True, encoding="utf-8")

    # Test Redis connection (ping)
    try:
        await redis.ping()
        yield redis  # Return the redis object to tests
    except Exception as e:
        pytest.fail(f"Redis connection failed: {str(e)}")
    finally:
        # Close connection after test completion
        await redis.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def auth_app(redis_connection):
    """Create a session-scoped auth app"""

    from auth.run import app
    from auth.src.connectors import init_db

    try:

        app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret-key",
            JWT_SECRET_KEY="test-secret-key",
        )

        class AsyncRedisMock:
            def __init__(self):
                self._data = {}
                self._data["SECRET_KEY"] = "test-secret-key"

            async def get(self, key):
                return self._data.get(key)

            async def set(self, key, value, ex=None):
                self._data[key] = value

            async def ping(self):
                return True

            async def close(self):
                pass

        app.redis = redis_connection
        app.conn, app.pool_manager = await init_db(app)

        async with app.app_context():
            await app.set_shared_secret()
            app.register_routes()
            yield app
            await app.clean_up()
            await asyncio.sleep(10)

    except Exception as e:
        logger.error(f"Error in auth_app fixture: {str(e)}")
        raise
    finally:
        if hasattr(app, "redis"):
            await app.redis.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def auth_client(auth_app):
    """Create a test client"""
    try:
        async with auth_app.test_client() as test_client:
            async with auth_app.app_context():
                yield test_client
    except Exception as e:
        logger.error(f"Error in auth_client fixture: {str(e)}")
        raise


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def bearer(auth_client, mock_user):
    """Create a test bearer token"""
    try:
        response = await auth_client.post("/auth/login", json=mock_user)
        assert response.status_code == 200
        data = await response.get_json()
        return data["access_token"]
    except Exception as e:
        logger.error(f"Error generating bearer token: {str(e)}")
        raise


@pytest.fixture(scope="session")
def mock_user():
    return {
        "first_name": "John",
        "last_name": "Doe",
        "email": "dylee@tutamail.com",
        "password": "testingTs",
        "confirm_password": "testingTs",
        "username": fake.user_name(),
        "host": "test",
        "id": "test",
    }


from werkzeug.datastructures import MultiDict


@pytest.fixture(scope="session")
def mock_event():
    event = {
        "title": fake.catch_phrase(),
        "description": fake.text(),
        "location": fake.address(),
        "price": fake.numerify("##"),
        "host": "test",
        "id": "test",
        "time": (datetime.utcnow() + timedelta(days=1)).isoformat() + "Z",
        "coordinates[]": [str(fake.longitude()), str(fake.latitude())],
    }
    event = MultiDict(event)
    event.add("categories[]", "beach")
    event.add("categories[]", "outdoor")

    return event


def pytest_addoption(parser):
    """Add custom command-line options for testing."""
    parser.addoption(
        "--env", action="store", default="test", help="Specify the test environment"
    )
    parser.addoption(
        "--profile",
        action="store_true",
        default=False,
        help="Enable performance profiling",
    )


@pytest.fixture(scope="session")
def environment(request):
    """Determine the test environment."""
    return request.config.getoption("--env")


@pytest.fixture(scope="session")
def performance_profiling(request):
    """Enable performance profiling if requested."""
    return request.config.getoption("--profile")


def pytest_configure(config):
    """Configure pytest markers and settings."""
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line(
        "markers", "performance: mark test for performance evaluation"
    )


# def pytest_terminal_summary(terminalreporter, exitstatus, config):
#     """Custom terminal summary for test run."""
#     passed = len(terminalreporter.stats.get("passed", []))
#     failed = len(terminalreporter.stats.get("failed", []))
#     skipped = len(terminalreporter.stats.get("skipped", []))

#     logger.info(f"\nTest Summary:")
#     logger.info(f"Passed: {passed}")
#     logger.info(f"Failed: {failed}")
#     logger.info(f"Skipped: {skipped}")
