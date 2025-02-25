
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
def event_loop():
    """Create an instance of the default event loop for each test case."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()

@pytest.fixture(scope='session')
def test_config():
    return {
        "REDIS_URI" : "redis://default:dQOWKWUYVSTqS7GB2Fjio4SIb05wOMwN@redis-14077.c16.us-east-1-2.ec2.redns.redis-cloud.com",
        "SURREAL_URI" : "ws://localhost:8000",
        "SURREAL_PASS" : "root",
        "SURREAL_USER" : "root"
        }

@pytest_asyncio.fixture
async def async_client(auth_app):
    """Create an async HTTP client for testing."""
    async with auth_app.test_client() as test_client:
        yield test_client

@pytest_asyncio.fixture(scope='session')
async def surreal(event_loop, test_config):
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


@pytest_asyncio.fixture(scope='session', autouse=True)
async def auth_app(surreal, test_config):
    os.environ["CONFIG_FILE"] = ""
    os.environ["ENVIRONMENT"] = "dev"
    os.environ["USE_FAKE_REDIS"] = "true"
    os.environ["NOVU_SECRET_KEY"] = "26fa1c421a0fb45df02a0d63adffaa1e"

    from auth.run import app
    from auth.src.connectors import AuthDB  # Add this import
    
    # Set config
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
    
    # Wrap the surreal connection with AuthDB
    app.db = AuthDB(surreal)

    # Register routes before testing
    async with app.app_context():
        await app.set_shared_secret()
        app.register_routes()
    
    return app

@pytest_asyncio.fixture
async def client(auth_app):
    """Create a test client"""
    async with auth_app.test_client() as test_client:
        yield test_client

@pytest.fixture
def mock_user():
    return {
        "first_name": "John",
        "last_name": "Doe",
        "email": "oyinxdoubx@gmail.com",
        "password": "testingTs",
        "confirm_password": "testingTs"
    }

@pytest.fixture(scope='session')
async def mock_redis():
    """Create a mock Redis instance"""
    class AsyncRedisMock:
        def __init__(self):
            self._data = {}
        
        async def get(self, key):
            return self._data.get(key)
            
        async def set(self, key, value, ex=None):
            self._data[key] = value
            
        async def delete(self, key):
            return self._data.pop(key, None)
            
        async def ping(self):
            return True
            
        async def close(self):
            pass

        @classmethod
        def from_url(cls, *args, **kwargs):
            return cls()
    
    return AsyncRedisMock()

@pytest.fixture(scope='function')
def mock_file_storage():
    """Mock file storage for media tests."""
    class MockFileStorage:
        def __init__(self):
            self.files = {}
        
        def save(self, file_data, metadata=None):
            file_id = fake.uuid4()
            self.files[file_id] = {
                'data': file_data,
                'metadata': metadata or {},
                'created_at': datetime.now().isoformat()
            }
            return file_id
        
        def get(self, file_id):
            return self.files.get(file_id)
        
        def delete(self, file_id):
            if file_id in self.files:
                del self.files[file_id]
                return True
            return False
    
    return MockFileStorage()

@pytest.fixture(scope='function')
def mock_stream_manager():
    """Mock stream manager for livestream tests."""
    class MockStreamManager:
        def __init__(self):
            self.streams = {}
        
        def create_stream(self, stream_data):
            stream_id = fake.uuid4()
            stream_data.update({
                'id': stream_id,
                'stream_key': fake.uuid4(),
                'rtmp_url': f'rtmp://streaming.example.com/{stream_id}',
                'status': 'created',
                'viewer_count': 0,
                'created_at': datetime.now().isoformat()
            })
            self.streams[stream_id] = stream_data
            return stream_data
        
        def get_stream(self, stream_id):
            return self.streams.get(stream_id)
        
        def update_stream(self, stream_id, data):
            if stream_id in self.streams:
                self.streams[stream_id].update(data)
                return self.streams[stream_id]
            return None
    
    return MockStreamManager()

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