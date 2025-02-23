
import os
import pytest
from faker import Faker
import asyncio
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global Faker instance for generating test data
fake = Faker()

@pytest.fixture(scope='session')
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope='module')
def test_config():
    """Provide test configuration."""
    return {
        'base_url': os.getenv('TEST_BASE_URL', 'http://localhost:8000'),
        'auth_token': os.getenv('TEST_AUTH_TOKEN', ''),
        'test_user': {
            'username': fake.user_name(),
            'email': fake.email(),
            'password': fake.password()
        }
    }

@pytest.fixture(scope='function')
def mock_db():
    """Create a mock database for isolated testing."""
    # Implement database mocking logic
    class MockDatabase:
        def __init__(self):
            self.data = {}
        
        def insert(self, collection, data):
            if collection not in self.data:
                self.data[collection] = []
            self.data[collection].append(data)
            return len(self.data[collection]) - 1
        
        def find(self, collection, query=None):
            return self.data.get(collection, [])
    
    return MockDatabase()

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