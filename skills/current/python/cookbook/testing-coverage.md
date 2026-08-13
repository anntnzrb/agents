# Testing Cookbook: Coverage and Organization
Coverage reports, exclusions, test layout, markers, pytest commands.

## Coverage reports

```bash
# Basic coverage
uv run pytest --cov=src

# With missing lines
uv run pytest --cov=src --cov-report=term-missing

# HTML report
uv run pytest --cov=src --cov-report=html
open htmlcov/index.html

# Fail if below threshold
uv run pytest --cov=src --cov-fail-under=80
```

During development, use `--cov-report=term-missing` to see uncovered lines; use HTML reports for detailed analysis.

## Coverage exclusions

```toml
# pyproject.toml
[tool.coverage.run]
source = ["src"]
branch = true
omit = ["tests/*", "*/__main__.py"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise NotImplementedError",
    "if TYPE_CHECKING:",
]
fail_under = 80
```

`branch = true` measures branch coverage, not only line coverage.

## Test layout

```text
tests/
|-- conftest.py           # Shared fixtures
|-- unit/
|   |-- test_entities.py
|   `-- test_services.py
|-- integration/
|   `-- test_api.py
`-- e2e/
    `-- test_workflow.py
```

Place shared fixtures in each level's `conftest.py`; they are available to tests in that directory and its subdirectories.

## Test markers

```python
import pytest

@pytest.mark.slow
def test_slow_operation():
    ...

@pytest.mark.integration
def test_database_integration():
    ...

# Run only fast tests
# uv run pytest -m "not slow"

# Run only integration tests
# uv run pytest -m integration
```

Define markers with descriptions in `pyproject.toml`; enable `--strict-markers`.

## pytest commands

```bash
# Run all tests
uv run pytest

# Verbose output
uv run pytest -v

# Stop on first failure
uv run pytest -x

# Run specific test
uv run pytest tests/test_user.py::TestUser::test_creation

# Run tests matching pattern
uv run pytest -k "user and not slow"

# Show print statements
uv run pytest -s

# Run last failed
uv run pytest --lf

# Parallel execution (requires pytest-xdist)
uv run pytest -n auto
```

Development iteration: `pytest -x --lf` stops on the first failure, then reruns only failures on the next run.
