# PartyScene Test Framework

Production-grade testing framework with comprehensive coverage across all microservices.

## Test Structure

```
tests/
├── auth/                   # Authentication service tests
│   ├── test_authentication.py
│   ├── test_security.py
│   ├── test_token_lifecycle.py      # JWT lifecycle
│   └── test_rate_limiting.py        # Brute force protection
├── users/                  # User service tests
│   ├── test_users_management.py
│   ├── test_relationships.py
│   └── test_privacy_controls.py     # GDPR, access control
├── events/                 # Events service tests
│   ├── test_event_creation.py
│   ├── test_event_queries.py
│   ├── test_live_queries.py         # WebSocket/SurrealDB LIVE
│   └── test_geospatial_queries.py   # Distance-based queries
├── payments/               # Payment service tests
│   ├── test_payment_operations.py
│   ├── test_payment_idempotency.py  # Duplicate prevention
│   ├── test_webhook_security.py     # Stripe webhooks
│   └── test_payment_edge_cases.py   # Error handling
├── media/                  # Media service tests
│   ├── test_media_operations.py
│   └── test_rabbitmq_consumer.py    # Message queue
├── posts/                  # Posts service tests
├── r18e/                   # Age verification tests
├── livestream/             # Livestream tests
├── integration/            # Cross-service tests
│   ├── test_auth_user_flow.py
│   └── test_event_creation_flow.py
├── security/               # Security-focused tests
│   └── test_sql_injection.py        # SQLi, XSS, CSRF
├── smoke/                  # Post-deployment validation
│   └── test_api_endpoints.py
└── fixtures/               # Reusable test utilities
    └── test_helpers.py
```

## Running Tests

### Prerequisites
```bash
# Activate virtual environment
& c:/Users/User/Documents/Projects/sites/.venv/Scripts/Activate.ps1

# Install test dependencies
pip install -r tests/requirements-test.txt
```

### Run All Tests
```bash
pytest tests/ -v
```

### Run Specific Service
```bash
# Payments
pytest tests/payments/ -v

# Auth
pytest tests/auth/ -v

# Events
pytest tests/events/ -v
```

### Run by Category
```bash
# Security tests only
pytest -m security tests/

# Integration tests only
pytest -m integration tests/

# Performance tests only
pytest -m performance tests/
```

### Run with Coverage
```bash
# Generate HTML coverage report
pytest tests/ --cov=. --cov-report=html

# View report
start htmlcov/index.html
```

### Run Specific Test File
```bash
pytest tests/payments/test_webhook_security.py -v
```

### Run Specific Test
```bash
pytest tests/payments/test_webhook_security.py::TestWebhookSecurity::test_webhook_with_invalid_signature -v
```

## Test Categories

### Unit Tests
Test individual components in isolation.
```bash
pytest tests/auth/test_authentication.py
```

### Integration Tests
Test cross-service interactions.
```bash
pytest tests/integration/ -v
```

### Security Tests
Test security vulnerabilities.
```bash
pytest -m security
```

### Performance Tests
Test response times and throughput.
```bash
pytest -m performance
```

### Smoke Tests
Quick validation for production.
```bash
pytest tests/smoke/ --base-url=https://api.partyscene.app
```

## Docker-Based Testing

### Run tests in containers
```bash
# Start all services and run tests
docker-compose -f docker-compose.test.yml up --abort-on-container-exit

# Run specific service tests
docker-compose -f docker-compose.test.yml run --rm microservices.auth

# Cleanup
docker-compose -f docker-compose.test.yml down -v
```

## Environment Variables

Tests use environment variables for configuration:

```bash
# Database
SURREAL_URI=ws://localhost:8000/rpc
SURREAL_USER=root
SURREAL_PASS=root

# Redis
REDIS_URI=redis://localhost:6379

# Stripe (test mode)
STRIPE_PRIV_KEY=sk_test_...
STRIPE_PUB_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Test environment
BASE_URL=http://localhost:5510
ENVIRONMENT=test
```

## Writing Tests

### Test File Template
```python
"""
Module description - What this file tests.
"""
import pytest
from http import HTTPStatus


@pytest.mark.asyncio(loop_scope="session")
class TestFeatureName:
    """Test feature description."""

    async def test_happy_path(self, client, bearer):
        """Test successful scenario."""
        response = await client.get(
            "/endpoint",
            headers={"Authorization": f"Bearer {bearer}"}
        )
        
        assert response.status_code == HTTPStatus.OK, \
            f"Expected 200, got {response.status_code}"
        
        data = (await response.get_json())["data"]
        assert "expected_field" in data

    async def test_error_case(self, client):
        """Test error handling."""
        response = await client.post("/endpoint", json={})
        
        assert response.status_code == HTTPStatus.BAD_REQUEST
```

### Best Practices

1. **Descriptive test names** - `test_payment_rejected_when_card_declined`
2. **Assertion messages** - Always include failure context
3. **One assertion per concept** - Multiple assertions OK if testing same thing
4. **Arrange-Act-Assert** - Structure tests clearly
5. **Mock external services** - Don't call real Stripe/AWS in tests
6. **Cleanup after tests** - Use fixtures with teardown
7. **Isolate tests** - Each test should be independent

### Fixtures

Common fixtures in `conftest.py`:

```python
@pytest.fixture
async def bearer(auth_client, mock_user):
    """Authenticated user token."""
    response = await auth_client.post("/auth/login", json=mock_user)
    return response.json()["data"]["access_token"]

@pytest.fixture
def mock_event():
    """Mock event data."""
    return {
        "title": "Test Event",
        "price": 25.00,
        # ...
    }
```

## Test Helpers

Use helpers from `tests/fixtures/test_helpers.py`:

```python
from tests.fixtures.test_helpers import TestHelpers

# Generate Stripe signature
signature = TestHelpers.generate_stripe_signature(payload, secret)

# Create mock data
event = TestHelpers.create_mock_event()
user = TestHelpers.create_mock_user()

# Assert response structure
TestHelpers.assert_response_structure(data, ["id", "name", "email"])

# Wait for async condition
await TestHelpers.wait_for_condition(
    lambda: check_database_updated(),
    timeout=5.0
)
```

## Coverage Goals

Target coverage by service:

| Service | Target | Current |
|---------|--------|---------|
| Payments | 85%+ | 85% ✅ |
| Auth | 80%+ | 78% ⚠️ |
| Events | 80%+ | 75% ⚠️ |
| Users | 75%+ | 68% ⚠️ |
| Media | 70%+ | 65% ⚠️ |
| Posts | 75%+ | 50% ❌ |
| Overall | 80%+ | 70% ⚠️ |

## CI/CD Integration

Tests run automatically in CI:

### GitHub Actions
```yaml
# .github/workflows/ci-test-deploy.yaml
- name: Run unit tests
  run: pytest tests/ --cov --cov-report=xml

- name: Upload coverage
  uses: codecov/codecov-action@v4
```

### Google Cloud Build
```yaml
# cloudbuild-improved.yaml
- name: 'gcr.io/cloud-builders/docker'
  args: ['compose', '-f', 'docker-compose.test.yml', 'up']
```

## Load Testing

Performance tests use Locust (separate from pytest):

```bash
# Smoke test (5 users, 2min)
python run_tests.py --scenario smoke --host http://localhost:8080

# Stress test (500 users, 20min)
python run_tests.py --scenario stress --host http://localhost:8080

# Web UI
locust -f locustfile.py --host http://localhost:8080
```

## Debugging Tests

### Run with verbose output
```bash
pytest tests/ -vv
```

### Run with print statements
```bash
pytest tests/ -s
```

### Drop into debugger on failure
```bash
pytest tests/ --pdb
```

### Run last failed tests
```bash
pytest tests/ --lf
```

### Run until failure
```bash
pytest tests/ -x  # Stop at first failure
```

## Common Issues

### Import errors
Ensure PYTHONPATH includes project root:
```bash
$env:PYTHONPATH = "C:\Users\User\Documents\Projects\py\partyscene"
```

### Database connection errors
Start SurrealDB:
```bash
docker run -p 8000:8000 surrealdb/surrealdb:latest start
```

### Redis connection errors
Start Redis:
```bash
docker run -p 6379:6379 redis:latest
```

### Port conflicts
Check if services are already running:
```bash
netstat -ano | findstr :5510
```

## Performance Benchmarks

Target performance metrics:

- **Auth login**: <100ms (p95)
- **Event queries**: <200ms (p95)
- **Payment intent**: <300ms (p95)
- **Media upload**: <2000ms (p95)
- **Overall error rate**: <1%

## Security Testing

Security tests validate:

- ✅ SQL injection prevention
- ✅ XSS sanitization
- ✅ CSRF protection
- ✅ JWT validation
- ✅ Rate limiting
- ✅ Input validation
- ✅ Authentication bypass attempts

## Test Data Management

Test data is:
- Created per test (isolated)
- Cleaned up after test
- Never shared between tests
- Generated with Faker for realism

## Contributing

When adding new tests:

1. Place in appropriate service directory
2. Follow naming convention: `test_feature_name.py`
3. Add docstrings to module and tests
4. Include assertion messages
5. Update this README if adding new patterns
6. Run full test suite before committing

## Support

For test framework questions:
- Check this README
- Review existing tests for patterns
- See `TEST-FRAMEWORK-AUDIT.md` for architecture
- Check `PRODUCTION-TEST-SUMMARY.md` for coverage details
