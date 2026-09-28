# Testing Cookbook: Async and Mocking

Pytest patterns: parameterized fixtures and tests, async tests with AnyIO, and mocking with `unittest.mock` and `httpx2.MockTransport`.

## Multiple backend implementations

Parameterized fixtures run each dependent test once per parameter; useful for database backends or configuration variants.

```python
import pytest

def create_database(db_type: str) -> dict[str, str | bool]:
    return {"type": db_type, "open": True}

@pytest.fixture(params=["postgres", "mysql", "sqlite"])
def database(request):
    """Run tests with multiple database backends."""
    db_type = request.param
    db = create_database(db_type)
    yield db
    db["open"] = False

def test_database_connection(database):
    assert database["open"] is True
```

## Factory fixtures

Return a callable for creating multiple objects with per-test custom attributes.

```python
from dataclasses import dataclass
import pytest

@dataclass(frozen=True, slots=True)
class User:
    name: str = "Test"
    age: int = 25

@pytest.fixture
def make_user():
    """Factory fixture for creating users with custom attributes."""
    def _make_user(name: str = "Test", age: int = 25) -> User:
        return User(name=name, age=age)
    return _make_user

def test_multiple_users(make_user):
    alice = make_user(name="Alice", age=30)
    bob = make_user(name="Bob", age=25)
    assert alice.name != bob.name
```

## Multiple input values

`parametrize` creates one test per input and output tuple, making failing inputs identifiable.

```python
import pytest

def double(x: int) -> int:
    return x * 2

@pytest.mark.parametrize("value,expected", [
    (1, 2),
    (2, 4),
    (3, 6),
    (0, 0),
    (-1, -2),
])
def test_double(value: int, expected: int):
    assert double(value) == expected
```

## All parameter combinations

Stacked `@pytest.mark.parametrize` decorators create the Cartesian product.

```python
import pytest

def multiply(x: int, y: int) -> int:
    return x * y

@pytest.mark.parametrize("x", [1, 2, 3])
@pytest.mark.parametrize("y", [10, 20])
def test_multiply(x: int, y: int):
    assert multiply(x, y) == x * y
```

## Descriptive test IDs

Custom IDs make output readable: `test_age_validation[adult]` rather than `test_age_validation[18-True]`.

```python
from dataclasses import dataclass
import pytest

@dataclass(frozen=True, slots=True)
class User:
    name: str
    age: int

@pytest.mark.parametrize("age,valid", [
    pytest.param(18, True, id="adult"),
    pytest.param(17, False, id="minor"),
    pytest.param(65, True, id="senior"),
    pytest.param(-1, False, id="negative"),
])
def test_age_validation(age: int, valid: bool):
    if valid:
        user = User(name="Test", age=age)
        assert user.age == age
    else:
        with pytest.raises(ValueError):
            if age < 0 or age < 18:
                raise ValueError("Invalid age")
            User(name="Test", age=age)
```

## Async tests with AnyIO

Mark async test functions with `@pytest.mark.anyio`. Define an `anyio_backend` fixture when pinning the test suite to asyncio. No `pytest-asyncio` plugin or `asyncio_mode` setting is required.

```python
from dataclasses import dataclass
import pytest

@dataclass(frozen=True, slots=True)
class User:
    name: str

class AsyncUserService:
    async def get_user(self, user_id: int) -> User:
        return User(name="Alice")

    async def get_users(self, ids: list[int]) -> list[User]:
        return [User(name="Alice") for _ in ids]

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.mark.anyio
async def test_fetch_user():
    service = AsyncUserService()
    user = await service.get_user(1)
    assert user.name == "Alice"

@pytest.mark.anyio
async def test_fetch_multiple_users():
    service = AsyncUserService()
    users = await service.get_users([1, 2, 3])
    assert len(users) == 3
```

## Async fixtures

Use async fixtures for lifecycle setup such as HTTP clients or database connections. Async generator fixtures automatically handle cleanup when exiting.

```python
import httpx2
import pytest

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
async def client():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"status": "ok"})

    transport = httpx2.MockTransport(handler)
    async with httpx2.AsyncClient(transport=transport, base_url="https://api.example.com") as c:
        yield c

@pytest.mark.anyio
async def test_api_call(client):
    response = await client.get("/users")
    assert response.status_code == 200
```

## Fake HTTP responses with MockTransport

Never mock HTTP client internals or use external network mocks. Use `httpx2.MockTransport` with a request handler function.

```python
import httpx2
import pytest

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def fake_client():
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/users/1":
            return httpx2.Response(200, json={"id": 1, "name": "Alice"})
        return httpx2.Response(404, json={"detail": "Not found"})

    transport = httpx2.MockTransport(handler)
    return httpx2.AsyncClient(transport=transport, base_url="https://api.example.com")

@pytest.mark.anyio
async def test_fetch_user_mock_transport(fake_client):
    async with fake_client as client:
        response = await client.get("/users/1")
        assert response.status_code == 200
        assert response.json()["name"] == "Alice"
```

## Mock external dependencies

Avoid calls to real databases or external APIs. Set `return_value` and verify calls with `assert_called_once()`.

```python
from unittest.mock import Mock

class UserService:
    def __init__(self, db: Mock) -> None:
        self.db = db

    def get_users(self) -> list[dict[str, object]]:
        return self.db.query()

def test_with_mock():
    mock_db = Mock()
    mock_db.query.return_value = [{"id": 1, "name": "Alice"}]

    service = UserService(db=mock_db)
    result = service.get_users()

    assert len(result) == 1
    mock_db.query.assert_called_once()
```

## Patch module-level functions

Patch at the full import path where the function is looked up (for example, `my_project.services.fetch_status`), not where it is originally defined.

```python
import sys
import types
from unittest.mock import patch

# Dotted lookup resolves where the function is imported and consumed:
service_module = types.ModuleType("service_module")
service_module.fetch_status = lambda: {"status": "unconfigured"}
sys.modules["service_module"] = service_module

def check_health() -> str:
    import service_module
    data = service_module.fetch_status()
    return data["status"]

@patch("service_module.fetch_status", return_value={"status": "healthy"})
def test_patch_function(mock_fetch):
    assert check_health() == "healthy"
    mock_fetch.assert_called_once()
```

## Mock async functions with AsyncMock

Use `AsyncMock` for coroutine functions. Verify awaits with `assert_awaited_once()` rather than `assert_called_once()`.

```python
from unittest.mock import AsyncMock
import pytest

class AsyncService:
    def __init__(self, api: AsyncMock) -> None:
        self.api = api

    async def process(self) -> dict[str, str]:
        return await self.api.fetch()

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def mock_api():
    api = AsyncMock()
    api.fetch.return_value = {"status": "ok"}
    return api

@pytest.mark.anyio
async def test_async_service(mock_api):
    service = AsyncService(api=mock_api)
    result = await service.process()

    assert result["status"] == "ok"
    mock_api.fetch.assert_awaited_once()
```

## Mock context managers

`MagicMock` implements magic methods including `__enter__`, `__exit__`, `__len__`, and `__iter__`.

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

`patch.object(..., wraps=...)` tracks invocations while executing the original implementation.

```python
from dataclasses import dataclass
from unittest.mock import patch

@dataclass
class Account:
    name: str
    validated: bool = False

    def validate(self) -> None:
        self.validated = True

def test_spy_on_method():
    account = Account(name="Alice")

    with patch.object(account, "validate", wraps=account.validate) as spy:
        account.validate()
        spy.assert_called_once()
        assert account.validated is True
```
