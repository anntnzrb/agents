# Library Defaults: Decision Tree

## Index

Use heading search; load only the task-matching section. Each domain lists the canonical 2026 choice, rationale, and usage. The skill MUST enforce these defaults unless the project's `pyproject.toml` explicitly says otherwise.

## CLI: typer

`typer`: type-annotated CLI generation. `argparse`: 5x more code; `click`: ignores type annotations; `fire`: scale-breaking magic. Single-function script: `typer.run(main)`. Subcommands: `@app.command()`.

```python
import typer
from rich import print as rprint

app = typer.Typer()


@app.command()
def greet(name: str, count: int = 1, shout: bool = False) -> None:
    """Print a greeting `count` times."""
    message = f"Hello, {name}!" if not shout else f"HELLO, {name.upper()}!"
    for _ in range(count):
        rprint(message)


if __name__ == "__main__":
    app()
```

## Terminal output: rich

Use `rich` for structured output: tables, progress bars, syntax highlighting, tracebacks. Plain `print` MAY serve non-interactive log lines; prefer `rich.console.Console(stderr=True).log(...)` even there. Install rich tracebacks once at process start.

```python
from rich.console import Console
from rich.table import Table

console = Console()

table = Table(title="Users")
table.add_column("ID", style="cyan")
table.add_column("Name", style="magenta")
table.add_row("1", "Alice")
console.print(table)

# Rich tracebacks (call once at process start)
from rich.traceback import install

install(show_locals=True)
```

## HTTP client: [httpx2](https://github.com/pydantic/httpx2)

`httpx2`: Pydantic-stewarded, sync+async, HTTP/2-native, brotli+zstd decoding, typed; replaces `requests`, `aiohttp`, and original `httpx`.

Install exactly `httpx2[http2,brotli,zstd]`; always include all three extras. Bare `httpx2.AsyncClient()` or `httpx2.Client()` is a bug. MUST use the factory pattern from `references/httpx2-optimization.md`, with all optimizations enabled by default. Load that reference whenever writing ANY network code; it also defines `create_client()` / `create_async_client()`, event hooks, and setting rationale.

```python
import socket
import httpx2

# ── Production defaults: ALL ON, always. ──
_LIMITS = httpx2.Limits(
    max_connections=200, max_keepalive_connections=40, keepalive_expiry=30.0
)
_TIMEOUT = httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)
_SOCKET_OPTS: list[tuple[int, int, int]] = [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]

# Async (the common case)
transport = httpx2.AsyncHTTPTransport(
    http2=True, retries=3, limits=_LIMITS, socket_options=_SOCKET_OPTS
)
async with httpx2.AsyncClient(
    transport=transport, timeout=_TIMEOUT, follow_redirects=True
) as client:
    response = await client.get("https://api.example.com/users")
    response.raise_for_status()
    users = response.json()

# Sync
transport = httpx2.HTTPTransport(
    http2=True, retries=3, limits=_LIMITS, socket_options=_SOCKET_OPTS
)
with httpx2.Client(
    transport=transport, timeout=_TIMEOUT, follow_redirects=True
) as client:
    response = client.get("https://api.example.com/users")
    response.raise_for_status()
    users = response.json()
```

## JSON: stdlib `json` (default) or `orjson` (hot paths)

Use stdlib `json` for cold paths/configs; use `orjson` when JSON is hot: cache layers, queue payloads, streaming responses, structured logs, or FastAPI raw `dict`/`list` responses. `orjson.dumps` returns `bytes`. For Pydantic v2, use `model_dump_json()`; pydantic-core (Rust) beats the `orjson + default=` bridge for Pydantic-shaped responses. FastAPI: `app = FastAPI(default_response_class=ORJSONResponse)`; Pydantic-typed responses correctly bypass it, while raw `dict`/`list` responses use orjson. See `references/orjson-stack.md` for the decision tree, flags, FastAPI, Redis/queue/logging patterns, and benchmark.

```python
import orjson

# orjson.dumps returns bytes, not str
raw: bytes = orjson.dumps(
    payload,
    option=orjson.OPT_NAIVE_UTC | orjson.OPT_UTC_Z | orjson.OPT_SERIALIZE_DATACLASS,
)
```

## Validation: pydantic v2

Use Pydantic v2 as the boundary validator for HTTP models, config (env vars via `pydantic-settings`), and anything entering from outside. Its Rust core is ~10x faster than v1. `@dataclass` is acceptable for internal records needing no validation; process-boundary data requires Pydantic.

```python
from pydantic import BaseModel, Field, EmailStr, field_validator


class User(BaseModel):
    id: int = Field(ge=1)
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    age: int | None = Field(default=None, ge=0, le=150)

    @field_validator("name")
    @classmethod
    def name_no_digits(cls, v: str) -> str:
        if any(c.isdigit() for c in v):
            raise ValueError("name cannot contain digits")
        return v


# Inside the program, use the validated instance with confidence
user = User.model_validate({"id": 1, "email": "a@b.com", "name": "Alice"})
print(user.model_dump_json(indent=2))
```

## Async: anyio

Full reference: [async-anyio.md](async-anyio.md). Use anyio; NEVER `import asyncio` directly. Called third-party libraries MAY use asyncio internally.

```python
import anyio


async def fetch(url: str) -> str:
    await anyio.sleep(0.1)
    return url


async def main() -> None:
    async with anyio.create_task_group() as tg:
        for url in ["a", "b", "c"]:
            tg.start_soon(fetch, url)


anyio.run(main)
```

## Web framework: fastapi

Type-hint-driven HTTP framework; Pydantic models automatically become OpenAPI schemas. Full database stack: [fastapi-stack.md](fastapi-stack.md).

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class CreateUser(BaseModel):
    name: str
    email: str


class User(BaseModel):
    id: int
    name: str
    email: str


@app.post("/users", response_model=User)
async def create_user(payload: CreateUser) -> User:
    return User(id=1, **payload.model_dump())
```

## ORM: sqlalchemy 2.x async

Use SQLAlchemy 2.x async with modern declarative `MappedAsDataclass` and type annotations. Full FastAPI integration: [fastapi-stack.md](fastapi-stack.md).

```python
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, MappedAsDataclass


class Base(MappedAsDataclass, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)


engine = create_async_engine("postgresql+asyncpg://localhost/myapp")
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
```

## Database: postgres + asyncpg

New applications: Postgres. SQLite MAY be used for tests, but NEVER production. `asyncpg` is the fastest Python Postgres driver and is native to SQLAlchemy 2.x async and FastAPI's lifespan model. URL: `postgresql+asyncpg://user:pass@host:5432/db`.

Migrations: Alembic, with `[alembic.context]` configured for the async engine.

```bash
uv add alembic
uv run alembic init -t async migrations
```

## TUI: textual

`textual`: rich, mouse-aware, mobile-style TUIs on the rich rendering engine. See [textual-tui.md](textual-tui.md).

## AI agents: pydantic-ai

`pydantic-ai`: Pydantic-team agent framework; type-strict, structured outputs first-class, model-agnostic. See [pydantic-ai.md](pydantic-ai.md).

## DataFrames: polars + numpy

Polars: 10-50x faster than pandas, real type system, lazy evaluation. Numpy remains for arrays. See [data-processing.md](data-processing.md).

## OLAP / SQL: duckdb

DuckDB: analytical SQL engine; queries CSV/Parquet/JSON directly without loading into memory, joins/aggregations 3-4x faster than Polars, zero-copy Polars interchange via Arrow. See [data-processing.md](data-processing.md).

## Tests: pytest

Use `unittest` for stdlib-only code; otherwise pytest. Conventions: files `test_*.py`; functions `test_*`; fixtures `@pytest.fixture`; async fixtures use `@pytest.fixture` on async functions under bundled `pytest-anyio`; parametrization `@pytest.mark.parametrize`; async tests `@pytest.mark.anyio` from anyio's pytest plugin.

```python
import pytest
import anyio


@pytest.fixture
def sample_user() -> dict[str, str]:
    return {"name": "Alice", "email": "a@b.com"}


@pytest.mark.parametrize("count,expected", [(1, "Hello"), (2, "Hello, Hello")])
def test_greet(count: int, expected: str) -> None:
    result = ", ".join(["Hello"] * count)
    assert result == expected


@pytest.mark.anyio
async def test_async_fetch() -> None:
    await anyio.sleep(0)
    assert True
```

```toml
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
addopts = ["-ra", "--strict-config", "--strict-markers"]
```

## Settings / config: pydantic-settings

Use `pydantic-settings` to load env vars and `.env` into a Pydantic model; it replaces ad-hoc `os.environ.get(...)`. The shown `Settings()` loads at import time and raises when required variables are missing.

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MYAPP_")

    database_url: str
    api_key: str = Field(min_length=1)
    debug: bool = False


settings = Settings()  # loads at import time; raises if any required var is missing
```

## Logging: stdlib logging + rich handler

Use stdlib `logging` with `rich.logging.RichHandler`; for production structured logs, use separate-dependency `structlog`, not a custom implementation.

```python
import logging
from rich.logging import RichHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
)
log = logging.getLogger(__name__)
log.info("ready")
```
