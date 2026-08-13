# Testing Cookbook: Basics

## Pytest + coverage

Install:

```bash
uv add --dev pytest pytest-cov pytest-asyncio
```

`pyproject.toml`:

```toml
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
addopts = """
    --cov=src
    --cov-report=term-missing
    --cov-report=html
    --cov-fail-under=80
    -v
    --strict-markers
"""
markers = [
    "slow: marks tests as slow",
    "integration: marks tests as integration tests",
]
asyncio_mode = "auto"
```

`asyncio_mode = "auto"` avoids `@pytest.mark.asyncio` on every async test.

## Basic unit tests

Test class methods, validation, and equality; `Test*` classes organize related tests and enable shared setup.

```python
# tests/test_entities.py
import pytest
from my_project.entities import User

class TestUser:
    def test_user_creation(self):
        user = User(name="Alice", email="alice@example.com")
        assert user.name == "Alice"
        assert user.email == "alice@example.com"

    def test_user_validation_raises(self):
        with pytest.raises(ValueError) as exc_info:
            User(name="", email="invalid")
        assert "name cannot be empty" in str(exc_info.value)

    def test_user_equality(self):
        user1 = User(name="Alice", email="a@b.com")
        user2 = User(name="Alice", email="a@b.com")
        assert user1 == user2
```

## Exceptions

`pytest.raises` checks exception type; `match` checks the message with a regex.

```python
def test_division_by_zero():
    with pytest.raises(ZeroDivisionError):
        1 / 0

def test_value_error_message():
    with pytest.raises(ValueError, match=r"must be positive"):
        create_user(age=-1)
```

## Floating-point comparison

Use `pytest.approx`; `abs` sets fixed-margin tolerance, `rel` percentage-based tolerance.

```python
def test_float_comparison():
    result = 0.1 + 0.2
    assert result == pytest.approx(0.3)

def test_with_tolerance():
    assert 2.0 == pytest.approx(2.1, abs=0.2)
    assert 2.0 == pytest.approx(2.02, rel=0.02)
```

## Reusable fixtures

Fixtures provide shared users/database connections and cleanup. Use `yield` for post-test cleanup.

```python
# tests/conftest.py
import pytest
from my_project.entities import User
from my_project.database import Database

@pytest.fixture
def user():
    """Create test user."""
    return User(name="Alice", email="alice@example.com")

@pytest.fixture
def database():
    """Create and cleanup test database."""
    db = Database(":memory:")
    db.create_tables()
    yield db
    db.close()

# tests/test_services.py
def test_save_user(database, user):
    database.save(user)
    assert database.get_user(user.id) == user
```

## Fixture scope

Use `scope="session"` for expensive one-time setup (such as database connections); use default `scope="function"` for test isolation.

```python
@pytest.fixture(scope="session")
def app():
    """Shared across all tests in session."""
    return create_app()

@pytest.fixture(scope="module")
def client(app):
    """Shared within a test module."""
    return app.test_client()

@pytest.fixture(scope="class")
def users():
    """Shared within a test class."""
    return [User(name=f"User{i}") for i in range(10)]

@pytest.fixture  # scope="function" is default
def temp_file():
    """Created fresh for each test."""
    with tempfile.NamedTemporaryFile() as f:
        yield f
```
