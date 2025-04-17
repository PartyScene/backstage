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
from unittest.mock import MagicMock, AsyncMock, patch
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global Faker instance for generating test data
fake = Faker()

# @pytest.fixture()
# def mock_stream():
#     return {
#             "title": fake.catch_phrase(),
#             "description": fake.text(max_nb_chars=200),
#             "scheduled_start": (datetime.now() + timedelta(hours=1)).isoformat(),
#             "category": fake.random_element(['gaming', 'music', 'talk-show', 'education']),
#             "tags": [fake.word() for _ in range(3)]
#         }


@pytest_asyncio.fixture(
    scope="session", loop_scope="session"
)  # Changed from module to session
async def media_app(redis_connection):
    from media.run import app
    from media.src.connectors import init_db

    # with patch('google.cloud.video.live_stream_v1.LivestreamServiceAsyncClient') as mock_client:
    #     # Create a mock async client
    #     mock_async_client = AsyncMock()
    #     mock_client.return_value = mock_async_client

    #     # Configure the mock client with predefined responses
    #     mock_async_client.create_stream.return_value = MagicMock()
    #     mock_async_client.get_stream.return_value = MagicMock()

    app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret-key",
        JWT_SECRET_KEY="test-secret-key",
    )

    # Initialize Redis mock
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
    try:
        async with app.app_context():
            await app.get_shared_secret()
            app.register_routes()
            yield app
            await app.clean_up()

    except Exception as e:
        logger.error(f"Error in media_app fixture: {str(e)}")
        raise
    finally:
        # Clean up resources
        if hasattr(app, "redis"):
            await app.redis.close()


@pytest_asyncio.fixture(scope="session")  # Changed from module to session
async def media_client(media_app, bearer):
    """Create an async HTTP client for testing."""
    try:
        async with media_app.test_client() as test_client:
            test_client.headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bearer}",
            }
            async with media_app.app_context():
                yield test_client
    except Exception as e:
        logger.error(f"Error in media_client fixture: {str(e)}")
        raise


# @pytest.fixture(scope="session")
# def mock_livestream():

#     with patch("livestream.src.views.base.LiveStream") as mock_livestream:
#         instance = mock_livestream.return_value
#         instance.start_stream = AsyncMock(return_value=True)
#         instance.get_stream = AsyncMock(return_value={"ingest_url": "test", "playback_url": "test", "id": "okPok"})
#         yield instance

# @pytest.fixture(scope='session')
# def environment(request):
#     """Determine the test environment."""
#     return request.config.getoption("--env")


@pytest.fixture(scope="session")
def performance_profiling(request):
    """Enable performance profiling if requested."""
    return request.config.getoption("--profile")


# def pytest_configure(config):
#     """Configure pytest markers and settings."""
#     config.addinivalue_line(
#         "markers",
#         "integration: mark test as an integration test"
#     )
#     config.addinivalue_line(
#         "markers",
#         "performance: mark test for performance evaluation"
#     )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Custom terminal summary for test run."""
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    skipped = len(terminalreporter.stats.get("skipped", []))

    logger.info(f"\nTest Summary:")
    logger.info(f"Passed: {passed}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Skipped: {skipped}")
