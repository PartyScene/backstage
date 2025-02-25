
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
from auth.src import AuthMicroService
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

# the custom event_loop fixture and update the async fixtures
@pytest.fixture(scope='session', autouse=True)
def event_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope='session', loop_scope="session")
async def surreal(test_config):
    """Create a session-scoped database connection"""
    db = AsyncSurreal(test_config['SURREAL_URI'])
    await db.connect(test_config['SURREAL_URI'])

    await db.signin(
        {
            'username': test_config['SURREAL_USER'],
            'password': test_config['SURREAL_PASS']
        }
    )
    await db.use('partyscene', 'partyscene')
    yield db
    await db.close()

@pytest_asyncio.fixture(scope='session', loop_scope="session")
async def auth_app(surreal, test_config):
    """Create a session-scoped auth app"""
    try:
        os.environ["CONFIG_FILE"] = ""
        os.environ["ENVIRONMENT"] = "dev"
        os.environ["USE_FAKE_REDIS"] = "true"
        os.environ["NOVU_SECRET_KEY"] = "26fa1c421a0fb45df02a0d63adffaa1e"

        from auth.run import app
        from auth.src.connectors import AuthDB

        app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret-key",
            JWT_SECRET_KEY="test-secret-key",
            **test_config
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

        app.redis = AsyncRedisMock()
        app.db = AuthDB(surreal)

        async with app.app_context():
            await app.set_shared_secret()
            app.register_routes()
            yield app
    except Exception as e:
        logger.error(f"Error in auth_app fixture: {str(e)}")
        raise
    finally:
        if hasattr(app, 'redis'):
            await app.redis.close()

@pytest_asyncio.fixture(scope='session')
async def auth_client(auth_app):
    """Create a test client"""
    try:
        async with auth_app.test_client() as test_client:
            async with auth_app.app_context():
                yield test_client
    except Exception as e:
        logger.error(f"Error in auth_client fixture: {str(e)}")
        raise

@pytest_asyncio.fixture(scope='session')
async def bearer(auth_client, mock_user):
    """Create a test bearer token"""
    try:
        response = await auth_client.post(
            "/login",
            json=mock_user
        )
        assert response.status_code == 200
        data = await response.get_json()
        return data['access_token']
    except Exception as e:
        logger.error(f"Error generating bearer token: {str(e)}")
        raise

@pytest.fixture(scope='session')
def mock_user():
    return {
        "first_name": "John",
        "last_name": "Doe",
        "email": "oyinxdoubx@gmail.com",
        "password": "testingTs",
        "confirm_password": "testingTs"
    }

def pytest_addoption(parser):
    """Add custom command-line options for testing."""
    parser.addoption(
        "--env",
        action="store",
        default="test",
        help="Specify the test environment"
    )
    parser.addoption(
        "--profile",
        action="store_true",
        default=False,
        help="Enable performance profiling"
    )

@pytest.fixture(scope='session')
def environment(request):
    """Determine the test environment."""
    return request.config.getoption("--env")

@pytest.fixture(scope='session')
def performance_profiling(request):
    """Enable performance profiling if requested."""
    return request.config.getoption("--profile")

def pytest_configure(config):
    """Configure pytest markers and settings."""
    config.addinivalue_line(
        "markers",
        "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers",
        "performance: mark test for performance evaluation"
    )

def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Custom terminal summary for test run."""
    passed = len(terminalreporter.stats.get('passed', []))
    failed = len(terminalreporter.stats.get('failed', []))
    skipped = len(terminalreporter.stats.get('skipped', []))
    
    logger.info(f"\nTest Summary:")
    logger.info(f"Passed: {passed}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Skipped: {skipped}")