# Running Tests on Windows - Quick Guide

## Prerequisites

1. **Python Virtual Environment**
   ```powershell
   & c:/Users/User/Documents/Projects/sites/.venv/Scripts/Activate.ps1
   ```

2. **Install Core Dependencies** (Minimal for basic tests)
   ```powershell
   python -m pip install pytest pytest-asyncio faker httpx stripe jwt redis surrealdb
   ```

3. **Required Services** (Docker)
   ```powershell
   # SurrealDB
   docker run -d -p 8000:8000 surrealdb/surrealdb:latest start
   
   # Redis
   docker run -d -p 6379:6379 redis:latest
   
   # RabbitMQ (for integration tests)
   docker run -d -p 5672:5672 -p 15672:15672 rabbitmq:3-management
   ```

## Environment Variables

Create `.env` file in project root:

```env
# Database
SURREAL_URI=ws://localhost:8000/rpc
SURREAL_USER=root
SURREAL_PASS=root

# Redis
REDIS_URI=redis://localhost:6379

# Stripe (test mode)
STRIPE_PRIV_KEY=sk_test_your_key_here
STRIPE_PUB_KEY=pk_test_your_key_here
STRIPE_WEBHOOK_SECRET=whsec_test_secret

# Auth
JWT_SECRET_KEY=test-secret-key-12345
SECRET_KEY=test-secret-key-12345

# Environment
ENVIRONMENT=test
```

## Running Tests

### Quick Validation (No Dependencies)
```powershell
# Test imports only
python -c "import pytest; import faker; import stripe; print('✅ Basic imports work')"
```

### Unit Tests (Minimal Dependencies)
```powershell
# Payments service
pytest tests/payments/test_payment_operations.py -v

# Auth service (requires SurrealDB + Redis)
pytest tests/auth/test_authentication.py -v -k "test_healthcheck"
```

### Integration Tests (Requires All Services)
```powershell
# Full payment flow
pytest tests/payments/ -v

# Full auth flow
pytest tests/auth/ -v

# Skip integration tests
pytest tests/ -v -m "not integration"
```

### With Coverage
```powershell
pytest tests/payments/ --cov=payments --cov-report=html
start htmlcov/index.html
```

## Expected Results

### Working Tests (After Fixes)
- ✅ `test_payment_operations.py` - Basic payment intent creation
- ✅ `test_payment_idempotency.py` - Input validation
- ✅ `test_webhook_security.py` - Signature verification (mocked)
- ✅ `test_authentication.py` - Login/register flows
- ✅ `test_token_lifecycle.py` - JWT validation

### Skipped Tests (Require Implementation)
- ⏭️ `test_rabbitmq_consumer.py` - RabbitMQ consumer not implemented
- ⏭️ `test_live_queries.py` - SurrealDB LIVE SELECT integration
- ⏭️ `test_geospatial_queries.py` - Geospatial query validation

### May Fail (Need Investigation)
- ⚠️ Tests requiring actual Stripe API calls
- ⚠️ Tests requiring GCP services (Storage, Secret Manager)
- ⚠️ Tests requiring specific database schema/data

## Troubleshooting

### Import Errors
```powershell
# Verify Python path
$env:PYTHONPATH = "C:\Users\User\Documents\Projects\py\partyscene"
```

### Connection Errors
```powershell
# Check if services are running
docker ps

# Check ports
netstat -ano | findstr "8000 6379 5672"
```

### Test Discovery Issues
```powershell
# Explicit test discovery
pytest --collect-only tests/payments/

# Run specific test
pytest tests/payments/test_payment_operations.py::TestPaymentOperations::test_create_payment_intent -v
```

### Fixture Errors
```powershell
# Check if conftest.py is found
pytest --fixtures tests/payments/

# Run with verbose fixture info
pytest tests/payments/ -v --setup-show
```

## Minimal Test Command

For quick validation without full setup:

```powershell
# Just test that files are valid Python
python -m py_compile tests/payments/test_payment_operations.py
python -m py_compile tests/auth/test_token_lifecycle.py

# Syntax check all test files
Get-ChildItem tests -Recurse -Filter "test_*.py" | ForEach-Object { python -m py_compile $_.FullName }
```

## Known Limitations on Windows

1. **uvloop** - Not available (fixed with conditional import)
2. **GCP Services** - Require credentials and network access
3. **Docker Services** - Must be running manually
4. **File Paths** - Use forward slashes in test data

## Success Criteria

✅ All test files import without errors  
✅ Basic unit tests pass (no external dependencies)  
✅ Integration tests pass (with Docker services running)  
✅ Coverage reports generate successfully  
✅ No Windows-specific errors (path, line endings, etc.)

## Next Steps After Basic Tests Pass

1. **Fix Failing Tests**
   - Document expected vs actual behavior
   - Update production code or test expectations
   - Add missing mocks/fixtures

2. **Add Missing Tests**
   - Events service comprehensive coverage
   - Users service privacy controls
   - Posts service CRUD operations

3. **Performance Testing**
   - Run load tests with Locust
   - Validate response times
   - Check memory usage

4. **CI/CD Integration**
   - Ensure tests pass in GitHub Actions
   - Configure Google Cloud Build
   - Set up automated deployment gates
