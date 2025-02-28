import pytest
import pytest_asyncio
# from ..conftest import auth_app, mock_user  # Import from parent conftest

@pytest_asyncio.fixture(scope='function')
async def auth_client(auth_app):
    """Create a test client specific for auth tests"""
    try:
        async with auth_app.test_client() as test_client:
            async with auth_app.app_context():
                yield test_client
    except Exception as e:
        logger.error(f"Error in auth_client fixture: {str(e)}")
        raise