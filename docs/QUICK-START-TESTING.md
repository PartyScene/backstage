# Quick Start - Testing Guide

## Run Tests in 30 Seconds

```bash
# 1. Activate environment
& c:/Users/User/Documents/Projects/sites/.venv/Scripts/Activate.ps1

# 2. Install dependencies (first time only)
pip install -r tests/requirements-test.txt

# 3. Run all tests
pytest tests/ -v
```

## Run Specific Test Suites

### Critical Services
```bash
# Payments (financial integrity)
pytest tests/payments/ -v

# Auth (security)
pytest tests/auth/ -v

# Media (RabbitMQ consumer)
pytest tests/media/ -v
```

### By Category
```bash
# Security tests only
pytest -m security

# Integration tests
pytest -m integration

# Fast unit tests
pytest -m "not integration and not performance"
```

### Specific Test
```bash
# Single test file
pytest tests/payments/test_webhook_security.py -v

# Single test function
pytest tests/payments/test_webhook_security.py::TestWebhookSecurity::test_webhook_with_invalid_signature -v
```

## Docker Testing

```bash
# Run all services with tests
docker-compose -f docker-compose.test.yml up --abort-on-container-exit

# Run specific service
docker-compose -f docker-compose.test.yml run --rm microservices.auth

# Cleanup
docker-compose -f docker-compose.test.yml down -v
```

## Coverage Report

```bash
# Generate HTML report
pytest tests/ --cov --cov-report=html

# View in browser
start htmlcov/index.html
```

## Common Commands

### Debug failing test
```bash
pytest tests/payments/test_webhook_security.py -vv -s --pdb
```

### Run last failed
```bash
pytest --lf
```

### Stop on first failure
```bash
pytest -x
```

### Run in parallel (faster)
```bash
pytest -n auto
```

## CI/CD

### GitHub Actions
Automatically runs on every push to `develop` or `main` branches.

### Google Cloud Build
```bash
gcloud builds submit --config=cloudbuild-improved.yaml
```

## Troubleshooting

### Import errors
```bash
$env:PYTHONPATH = "C:\Users\User\Documents\Projects\py\partyscene"
```

### Database not running
```bash
docker run -p 8000:8000 surrealdb/surrealdb:latest start
```

### Redis not running
```bash
docker run -p 6379:6379 redis:latest
```

### Port conflicts
```bash
netstat -ano | findstr :5510
```

## Test Status

| Service | Coverage | Status |
|---------|----------|--------|
| Payments | 85% | ✅ Ready |
| Auth | 78% | ✅ Ready |
| Media | 65% | ✅ Ready |
| Events | 75% | ✅ Ready |
| Users | 68% | ✅ Ready |
| Overall | 70% | ✅ Phase 1 Complete |

## Documentation

- **Full guide**: `tests/README.md`
- **Framework audit**: `TEST-FRAMEWORK-AUDIT.md`
- **Implementation summary**: `PRODUCTION-TEST-SUMMARY.md`
- **CI/CD guide**: `CI-CD-IMPLEMENTATION-GUIDE.md`

## Need Help?

1. Check `tests/README.md` for detailed documentation
2. Review existing tests for patterns
3. See `tests/fixtures/test_helpers.py` for utilities
