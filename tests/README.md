# Testing Documentation

## Overview

This directory contains the test suite for the IUU Fishing incident tracking system. Tests are organized into unit and integration tests, with comprehensive coverage of core functionality.

## Setup

### Install Dependencies

```bash
pip install -r requirements.txt
```

Key testing dependencies:
- `pytest` - Test framework
- `pytest-asyncio` - Async test support
- `pytest-cov` - Coverage reporting
- `httpx` - Async HTTP client for API tests

### Database Setup

Integration tests require a running MongoDB instance on port 27018 (as configured in docker-compose.override.yml).

Start the test database:
```bash
docker compose up -d
```

## Running Tests

### Run All Tests
```bash
pytest
```

### Run with Coverage
```bash
pytest --cov=app --cov-report=html
```

### Run Unit Tests Only
```bash
pytest tests/unit -m unit
```

### Run Integration Tests Only
```bash
pytest tests/integration -m integration
```

### Run Specific Test File
```bash
pytest tests/unit/test_services.py -v
```

### Run Specific Test Class or Function
```bash
pytest tests/unit/test_audit.py::TestAuditContext -v
pytest tests/unit/test_audit.py::TestAuditContext::test_set_and_get_user -v
```

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── unit/                    # Unit tests (no external dependencies)
│   ├── test_models.py       # Data model tests
│   ├── test_services.py     # Service layer tests
│   └── test_audit.py        # Audit system tests
└── integration/             # Integration tests (with database/API)
    └── test_api_endpoints.py # API endpoint tests
```

## Test Markers

Tests are marked with custom markers for organization:

- `@pytest.mark.unit` - Unit tests (fast, isolated)
- `@pytest.mark.integration` - Integration tests (requires database)
- `@pytest.mark.slow` - Tests that take longer to run
- `@pytest.mark.skip_ci` - Tests to skip in CI environment

Run tests by marker:
```bash
pytest -m unit
pytest -m "not slow"
```

## Fixtures

Common fixtures available in `conftest.py`:

- `test_db` - Initializes test database with Beanie
- `async_client` - Async HTTP client for API testing
- `sync_client` - Synchronous test client
- `sample_source` - Pre-created Source document
- `sample_incident` - Pre-created IncidentReport document
- `sample_user` - Pre-created User document
- `admin_user` - Pre-created admin User
- `mock_dspy` - Mocked DSPy for avoiding LLM calls
- `mock_openai` - Mocked OpenAI API calls

## Coverage Reports

After running tests with coverage:

- **Terminal**: Summary shown in terminal
- **HTML**: Open `htmlcov/index.html` in browser
- **XML**: `coverage.xml` for CI integration

## Current Test Coverage

### Completed
- Unit tests for data models (Pydantic and Beanie)
- Unit tests for service layer (IncidentService, SourceService, OverviewService)
- Unit tests for audit system (context, strategies)
- Integration tests for audit trail creation
- Integration tests for API endpoints (incidents, sources, overviews, logs)

### TODO (see beads issues)
- Tests for DSPy modules (content extraction, classification, analysis)
- Full pipeline integration tests (URL to incident)
- Authentication/authorization tests
- WebScraper tests
- Additional edge case coverage

## Best Practices

1. **Isolation**: Unit tests should mock external dependencies
2. **Database**: Use `test_db` fixture for database-dependent tests
3. **Async**: Use `@pytest.mark.asyncio` for async tests
4. **Naming**: Test functions should start with `test_`
5. **Assertions**: Use clear, specific assertions
6. **Cleanup**: Fixtures handle cleanup automatically
7. **Markers**: Add appropriate markers to new tests

## Common Issues

### Import Errors
If you get import errors, ensure you're in the project root and dependencies are installed:
```bash
pip install -r requirements.txt
```

### Database Connection Issues
Ensure MongoDB is running on port 27018:
```bash
docker compose ps
docker compose up -d
```

### Async Test Warnings
If you see warnings about async tests, ensure:
- Test function is marked with `@pytest.mark.asyncio`
- Async fixtures use `async def` and `await`

## Contributing Tests

When adding new tests:

1. Choose appropriate location (unit vs integration)
2. Add relevant markers
3. Use existing fixtures where possible
4. Mock external dependencies in unit tests
5. Update this README if adding new patterns
6. Ensure tests pass before committing

## CI/CD Integration

Tests can be run in CI pipelines. Example GitHub Actions:

```yaml
- name: Run tests
  run: |
    pytest --cov=app --cov-report=xml

- name: Upload coverage
  uses: codecov/codecov-action@v3
  with:
    files: ./coverage.xml
```
