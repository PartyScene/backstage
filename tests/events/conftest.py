
import os
import pprint
import sys


# Add project root and shared directories to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'shared'))

import pytest
import pytest_asyncio
from faker import Faker
import asyncio
import logging
import httpx
from datetime import datetime, timedelta
import io
from unittest.mock import MagicMock
from surrealdb import AsyncSurreal

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global Faker instance for generating test data
fake = Faker()

@pytest.fixture(scope='session')
def test_config():
    return {
        "REDIS_URI" : "redis://default:dQOWKWUYVSTqS7GB2Fjio4SIb05wOMwN@redis-14077.c16.us-east-1-2.ec2.redns.redis-cloud.com",
        "SURREAL_URI" : "ws://localhost:8000",
        "SURREAL_PASS" : "root",
        "SURREAL_USER" : "root"
        }

@pytest.fixture(scope="session")
def mock_event():
    return {
        "title": fake.catch_phrase(),
        "description": fake.text(),
        "start_time": (datetime.now() + timedelta(days=1)).isoformat(),
        "coordinates": fake.latlng(),
        "location": fake.address(),
        "price": fake.numerify('##'),
        }
        
@pytest_asyncio.fixture(scope='session', loop_scope="session")  # Changed from module to session
async def event_app(surreal, test_config):
    os.environ["CONFIG_FILE"] = ""
    os.environ["ENVIRONMENT"] = "dev"
    os.environ["USE_FAKE_REDIS"] = "true"
    os.environ["NOVU_SECRET_KEY"] = "26fa1c421a0fb45df02a0d63adffaa1e"

    from events.run import app
    from events.src.connectors import EventsDB
    app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret-key",
        JWT_SECRET_KEY="test-secret-key",
        **test_config
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

    app.redis = AsyncRedisMock()
    app.db = EventsDB(surreal)
    try:
        async with app.app_context():
            await app.get_shared_secret()
            app.register_routes()
            yield app
    except Exception as e:
        logger.error(f"Error in event_app fixture: {str(e)}")
        raise
    finally:
        # Clean up resources
        if hasattr(app, 'redis'):
            await app.redis.close()

@pytest_asyncio.fixture(scope='session')  # Changed from module to session
async def event_client(event_app, bearer):
    """Create an async HTTP client for testing."""
    try:
        async with event_app.test_client() as test_client:
            test_client.headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bearer}"
            }
            async with event_app.app_context():
                yield test_client
    except Exception as e:
        logger.error(f"Error in event_client fixture: {str(e)}")
        raise
# @pytest.fixture(scope='session')
# def environment(request):
#     """Determine the test environment."""
#     return request.config.getoption("--env")

# @pytest.fixture(scope='session')
# def performance_profiling(request):
#     """Enable performance profiling if requested."""
#     return request.config.getoption("--profile")

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
    passed = len(terminalreporter.stats.get('passed', []))
    failed = len(terminalreporter.stats.get('failed', []))
    skipped = len(terminalreporter.stats.get('skipped', []))
    
    logger.info(f"\nTest Summary:")
    logger.info(f"Passed: {passed}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Skipped: {skipped}")