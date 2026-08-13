# Testing Cookbook: Async and Mocking

Pytest patterns: parameterized fixtures/tests, async tests/fixtures, and `unittest.mock`.

## Multiple backend implementations

Parameterized fixtures run each dependent test once per parameter; useful for database backends/configurations.

```python
@pytest.fixture(params=["postgres", "mysql", "sqlite"])
def database(request):
    """Run tests with multiple database backends."""
    db_type = request.param
    db = create_database(db_type)
    yield db
    db.close()
```

## Factory fixtures

Return a callable for creating multiple objects with per-test custom attributes.

```python
@pytest.fixture
def make_user():
    """Factory fixture for creating users with custom attributes."""
    def _make_user(name: str = "Test", age: int = 25):
        return User(name=name, age=age)
    return _make_user

def test_multiple_users(make_user):
    alice = make_user(name="Alice", age=30)
    bob = make_user(name="Bob", age=25)
    assert alice.name != bob.name
```

## Multiple input values

`parametrize` creates one test per input/output tuple, making failing inputs identifiable.

```python
@pytest.mark.parametrize("input,expected", [
    (1, 2),
    (2, 4),
    (3, 6),
    (0, 0),
    (-1, -2),
])
def test_double(input, expected):
    assert double(input) == expected
```

## All parameter combinations

Stacked `@pytest.mark.parametrize` decorators create the cartesian product.

```python
@pytest.mark.parametrize("x", [1, 2, 3])
@pytest.mark.parametrize("y", [10, 20])
def test_multiply(x, y):
    # Runs 6 times: (1,10), (1,20), (2,10), (2,20), (3,10), (3,20)
    assert multiply(x, y) == x * y
```

## Descriptive test IDs

Custom IDs make output readable: `test_age_validation[adult]` rather than `test_age_validation[18-True]`.

```python
@pytest.mark.parametrize("age,valid", [
    pytest.param(18, True, id="adult"),
    pytest.param(17, False, id="minor"),
    pytest.param(65, True, id="senior"),
    pytest.param(-1, False, id="negative"),
])
def test_age_validation(age, valid):
    if valid:
        user = User(name="Test", age=age)
        assert user.age == age
    else:
        with pytest.raises(ValueError):
            User(name="Test", age=age)
```

## Async functions

Use `@pytest.mark.asyncio` for coroutine tests; with `asyncio_mode = "auto"` in config, the decorator may be omitted.

```python
# tests/test_async.py
import pytest
from my_project.services import AsyncUserService

@pytest.mark.asyncio
async def test_fetch_user():
    service = AsyncUserService()
    user = await service.get_user(1)
    assert user.name == "Alice"

@pytest.mark.asyncio
async def test_fetch_multiple_users():
    service = AsyncUserService()
    users = await service.get_users([1, 2, 3])
    assert len(users) == 3
```

## Async fixtures

Use async fixtures for setup such as HTTP clients or database connections; async generators automatically handle async context-manager cleanup.

```python
@pytest.fixture
async def async_client():
    import httpx
    async with httpx.AsyncClient() as client:
        yield client

@pytest.mark.asyncio
async def test_api_call(async_client):
    response = await async_client.get("https://api.example.com/users")
    assert response.status_code == 200
```

## Mock external dependencies

Avoid calls to real databases/external APIs. Set `return_value`; verify use with `assert_called_once()`.

```python
from unittest.mock import Mock, patch, AsyncMock

def test_with_mock():
    mock_db = Mock()
    mock_db.query.return_value = [{"id": 1, "name": "Alice"}]

    service = UserService(db=mock_db)
    result = service.get_users()

    assert len(result) == 1
    mock_db.query.assert_called_once()
```

## Patch module-level functions

Patch at the full import path where the function is used, not where defined: `my_project.services.requests`, not `requests`.

```python
@patch("my_project.services.requests.get")
def test_external_api(mock_get):
    mock_get.return_value.json.return_value = {"status": "ok"}

    result = call_external_api()

    assert result["status"] == "ok"
    mock_get.assert_called_once()

def test_with_context_manager():
    with patch("my_project.services.database") as mock_db:
        mock_db.query.return_value = []
        result = get_users()
        assert result == []
```

## Mock async functions

Use `AsyncMock`, not `Mock`, for async functions; verify awaits with `assert_awaited_once()`, not `assert_called_once()`.

```python
@pytest.fixture
async def mock_api():
    api = AsyncMock()
    api.fetch.return_value = {"status": "ok"}
    return api

@pytest.mark.asyncio
async def test_async_service(mock_api):
    service = AsyncService(api=mock_api)
    result = await service.process()

    assert result["status"] == "ok"
    mock_api.fetch.assert_awaited_once()
```

## Mock context managers

`MagicMock` automatically implements magic methods including `__enter__`, `__exit__`, `__len__`, and `__iter__`.

```python
from unittest.mock import MagicMock

def test_context_manager():
    mock_file = MagicMock()
    mock_file.__enter__.return_value = mock_file
    mock_file.read.return_value = "content"

    with mock_file as f:
        assert f.read() == "content"
```

## Spy on real objects

`patch.object(..., wraps=...)` tracks calls while executing the original implementation.

```python
from unittest.mock import patch

def test_spy_on_method():
    user = User(name="Alice")

    with patch.object(user, "validate", wraps=user.validate) as spy:
        user.save()
        spy.assert_called_once()
```
