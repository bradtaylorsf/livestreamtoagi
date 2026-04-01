---
name: python-testing
description: Python testing patterns with pytest, FastAPI TestClient, and async testing. Use when writing Python tests in this project.
auto_load: true
priority: high
---

# Python Testing Patterns

## Trigger
When writing tests for this Python/FastAPI project.

## Project Test Stack
- **Runner**: pytest with pytest-asyncio
- **Framework**: FastAPI with TestClient (httpx-based)
- **Async**: pytest-asyncio with `asyncio_mode = "auto"`
- **Database**: asyncpg (mocked in unit tests, real in integration tests)
- **Cache**: Redis (mocked in unit tests, real in integration tests)

## Critical Rules

### 1. NEVER instantiate TestClient at module level

```python
# ❌ CRITICAL — triggers lifespan at import, requires Docker
from core.main import app
from fastapi.testclient import TestClient
client = TestClient(app)  # Connects to DB/Redis on import!

def test_health():
    response = client.get("/health")

# ✅ CORRECT — isolated per test, can mock lifespan
from core.main import app
from fastapi.testclient import TestClient

def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
```

### 2. Mock lifespan dependencies for unit tests

```python
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    """TestClient with mocked DB and Redis."""
    with patch("core.main.get_db_pool", new_callable=AsyncMock), \
         patch("core.main.get_redis", new_callable=AsyncMock):
        from core.main import app
        with TestClient(app) as c:
            yield c

def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
```

### 3. Guard integration tests with skipif

```python
import os
import pytest

requires_docker = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — Docker services required"
)

@requires_docker
async def test_db_connection():
    # This only runs when Docker is available
    ...
```

### 4. Verify Docker health before integration tests

Always run before test execution:
```bash
docker compose up -d && bash scripts/check-services.sh
```

All 5 checks must pass (Redis, PostgreSQL, pgvector, pg_trgm, Langfuse) before running integration tests.

## Test Organization

```
tests/
├── unit/           # No Docker required, fast
│   ├── test_models.py
│   └── test_endpoints.py
├── integration/    # Docker required, guarded with skipif
│   ├── test_db.py
│   └── test_redis.py
└── conftest.py     # Shared fixtures
```

## Async Testing

```python
import pytest

@pytest.mark.asyncio
async def test_async_operation():
    result = await some_async_function()
    assert result == expected
```

## Anti-Patterns to Avoid

- Module-level side effects in test files (imports that connect to services)
- Hard-coded test data IDs that depend on database state
- Tests that depend on execution order
- Using `Any` type assertions to make tests pass
- Not capturing stderr/stdout from failed test runs (makes retry diagnosis impossible)
