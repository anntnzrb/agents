
# Python Programmer

> **Precedence:** Policy lives in SKILL.md and cookbook/modern.md. This directory contains opinionated recipes that MUST NOT contradict that policy. An inherited project's existing configuration, declared Python target, lockfiles, and stack override stack defaults; new code follows the policy.

## Index

Read the section whose heading matches the task; use heading search before loading unrelated detail.

Modern Python. Type-strict, stack-first, async-correct.

## Philosophy

The type checker is your compiler. Make illegal states unrepresentable. Parse at boundaries. Own resources explicitly. Every function has a contract; the type system enforces it.

## Hard rules

These are deliberate project choices. Violations are always wrong, not "style preferences".

### Tooling

The canonical tooling stack and policy defaults are defined in `SKILL.md` `## Stack`. This section details the coding rules enforced across recipes.
### The iron list

1. **Frozen by default**: `@dataclass(frozen=True, slots=True)`. Pydantic: `model_config = ConfigDict(frozen=True)`. Mutable only when mutation is the documented purpose
2. **NewType for distinct IDs**: `UserId = NewType("UserId", int)`. Never pass raw `int` where a branded type exists
3. **`match` only for variants, `if` only for booleans**: **NEVER** use `if/elif/else` to discriminate on type (`isinstance`), enum value, or literal variant. `match/case` is mandatory for these; non-negotiable. **ALWAYS** end with `case _ as unreachable: assert_never(unreachable)`; bare `case _: pass` and `case _: raise ValueError` are banned (they silently swallow new variants). `if/else` is fine for boolean expressions, range checks, and predicate calls that aren't variant discrimination. A single `isinstance` check that narrows one value (for example, narrowing `object` at a boundary) is fine. See "Why `if/elif` on variants is banned" below for examples
4. **Protocol over ABC**: `typing.Protocol` for interfaces. ABC only when you need shared method implementation
5. **No raw dicts in signatures**: params and returns use `TypedDict`, `dataclass`, or Pydantic model. Internal scratch dicts are fine
6. **Parse, don't validate**: constructors produce typed objects or raise. Never pass unvalidated data deeper into the call stack
7. **Typed errors**: error types are dataclasses or exceptions with typed fields. Never `raise ValueError("something")` with a bare string. Use union returns when the caller is within 1-2 call levels and must handle the outcome (repository → service). Use exceptions when the error should propagate up many layers to a boundary handler (service → HTTP handler)
8. **Final for constants**: module-level constants use `Final`. Mutable module globals are a code smell
9. **Explicit None**: annotate `-> X | None`. Never return `None` from a function whose signature omits it
10. **Context managers for resources**: files, DB connections, HTTP clients, locks. No manual `.close()`
11. **Any is banned; object only for unknown values**: `Any` is banned in annotations; when a third-party signature forces it, contain it at the boundary and narrow immediately. `object` is the correct annotation for a genuinely unknown value (for example `__eq__(self, other: object)` or boundary inputs narrowed with `isinstance`/`match`). NEVER use `object` where a Protocol, PEP 695 type parameter, union, or TypedDict can express the shape
12. **No cast**: `cast()` is banned. Redesign the types
13. **No type: ignore**; fix the type error. The checker is right; you are wrong
14. **Specific except by default**: catch the specific exception you expect. `except Exception` is permitted only at process, request, or task boundaries, and only to log and then re-raise or map; mark it with `# noqa: BLE001 - <reason>`. Bare `except:` and `except BaseException` are never allowed
15. **CLI**: `typer` + `rich` for multi-command applications; stdlib `argparse` for zero-dependency single-file scripts (including skill `scripts/cli.py` entrypoints). Never click or fire

### Typing and safety

- Universal idioms, baseline syntax, and the Never table are defined in `cookbook/modern.md`
- `basedpyright` in `typeCheckingMode = "all"`. Every public function has full annotations. Internal helpers: annotate return type; parameter types may be inferred
- `ruff` with `select = ["ALL"]`. Override specific rules per project in `pyproject.toml`, never globally disable the strict baseline
- Every new function must have a `docstring` unless its name + signature makes it completely obvious (e.g. `def full_name(first: str, last: str) -> str:`)

### Any and object handling

`Any` is banned in type annotations. When a third-party signature forces it, isolate it at the boundary and narrow immediately. `object` is the top type and the correct annotation for genuinely unknown values (such as `__eq__(self, other: object)` or untrusted payloads), which must be narrowed with `isinstance` or `match`. NEVER use `object` where a Protocol, PEP 695 type parameter, union, or TypedDict can express the shape.

```python
# BANNED: Any in annotations
def process(data: Any) -> Any: ...


# BANNED: object where a structured type is known
def store(items: list[object]) -> None: ...  # use list[T] or list[Item]


# GOOD: object for genuinely unknown values, narrowed immediately
def parse_payload(raw: object) -> Document:
    if isinstance(raw, bytes):
        return Document.from_bytes(raw)
    if isinstance(raw, str):
        return Document.from_str(raw)
    raise TypeError(f"unsupported payload type: {type(raw).__name__}")


# GOOD: Protocol for structural typing
class Serializable(Protocol):
    def serialize(self) -> bytes: ...


def process(data: Serializable) -> ProcessResult: ...


# GOOD: PEP 695 generic pass-through
def identity[T](x: T) -> T: ...
def first[T](items: Sequence[T]) -> T: ...


# GOOD: explicit union for known variants
def parse(raw: str | bytes) -> Document: ...
```

### Why `if/elif` on variants is banned

`if/elif/else` chains on type, enum, or literal values lose compile-time exhaustiveness. When a new variant is added, nothing warns you. `match/case` + `assert_never` does.

```python
# BANNED: if/elif for type discrimination
if isinstance(event, Click):
    handle_click(event.x, event.y)
elif isinstance(event, Scroll):
    handle_scroll(event.delta)
else:
    raise ValueError(f"Unknown: {event}")  # runtime bomb

# BANNED: if/elif for enum discrimination
if status == Status.PENDING:
    start_review()
elif status == Status.ACTIVE:
    continue_processing()
elif status == Status.CLOSED:
    archive()

# BANNED: non-exhaustive match (swallows new variants)
match event:
    case Click(x, y):
        handle_click(x, y)
    case _:
        pass

# GOOD: exhaustive match with assert_never
match event:
    case Click(x=x, y=y):
        handle_click(x, y)
    case Scroll(delta=delta):
        handle_scroll(delta)
    case _ as unreachable:
        assert_never(unreachable)

# GOOD: enum match
match status:
    case Status.PENDING:
        start_review()
    case Status.ACTIVE:
        continue_processing()
    case Status.CLOSED:
        archive()
    case _ as unreachable:
        assert_never(unreachable)
```

`if/else` is fine for boolean conditions and range checks; things that aren't variant discrimination:

```python
# FINE: boolean, not variant
if age >= 18:
    grant_access()
else:
    deny_access()
```

### Why broad `except` is banned

`except Exception` catches **every** non-system exception; `KeyError`, `TypeError`, `AttributeError`, `ValueError` all vanish. You lose the stack trace that would have told you exactly what went wrong. The fix is always to name the exception you expect.

```python
# BANNED: swallows bugs
try:
    result = api.fetch(url)
except Exception as e:
    logger.error(e)
    return None

# BANNED: catch-and-ignore
try:
    parse(data)
except Exception:
    pass

# GOOD: catch what you expect
try:
    result = api.fetch(url)
except httpx2.HTTPStatusError as e:
    logger.error("API %d: %s", e.response.status_code, e.request.url)
    return None
except httpx2.ConnectError:
    raise ServiceUnavailableError(service="api") from None


# GOOD: top-level boundary (only place broad catch is acceptable)
def main() -> int:
    try:
        return run()
    except Exception:  # noqa: BLE001 - process boundary logs and maps to exit code
        logger.exception("unhandled error")
        return 1
```

### Async

- `import asyncio` is banned in new code. Use `import anyio`
- For background tasks, use `anyio.create_task_group`. Never fire-and-forget with `asyncio.create_task`
- For concurrency gates, use `anyio.CapacityLimiter` (not `asyncio.Semaphore`)
- Load `../../cookbook/async.md` for the full async guide

### Data modeling: which container, when

All model fields carry type annotations. No `Any`, no untyped dicts in public APIs.
Use `polars` + `duckdb` for data. pandas is never the right answer in this stack.

| Situation | Use |
|---|---|
| User input, API request/response | `Pydantic BaseModel (frozen=True)` |
| Internal value object (no I/O) | `@dataclass(frozen=True, slots=True)` |
| Function with multiple outcomes | Union of frozen dataclasses + `match` |
| Dict shape for JSON compat / `**kwargs` | `TypedDict` |
| Fixed constants | `StrEnum` / `IntEnum` |
| Distinct primitive (UserId vs MovieId) | `NewType` |
| Contract / capability | `Protocol` |
| Contract + shared implementation | `ABC` |
| ORM model (SQLAlchemy) | `Mapped[]`: inherently mutable |
| Config from env vars | `pydantic-settings BaseSettings` |

**The one rule**: data crosses trust boundary → Pydantic. Everything else → dataclass.

Load `data-modeling.md` for the full decision flowchart and comparison matrix.

### When frozen=True does not apply

- **ORM models**: SQLAlchemy `Mapped[]` requires mutation
- **Builder / accumulator**: object exists to be mutated (counter, buffer, state machine). Docstring must explain why
- **Pydantic Settings**: tests override fields. Mutable is acceptable

### Libraries

Canonical defaults (override only if `pyproject.toml` explicitly picks something else):

| Domain | Library | Reason |
|---|---|---|
| CLI | `typer` | Type-annotated CLI from function sigs |
| Pretty output | `rich` | Tables, progress, tracebacks, markdown |
| HTTP client | [`httpx2`](https://github.com/pydantic/httpx2) | Next-gen HTTP client (Pydantic stewardship), HTTP/2, brotli+zstd. Always `httpx2[http2,brotli,zstd]`. See `httpx2-optimization.md` |
| Validation | `pydantic` v2 | Fast native validator, JSON Schema |
| Web API | `fastapi` | Async, Pydantic-native, OpenAPI |
| ORM | `sqlalchemy` 2.x async | `Mapped[]` types, async sessions |
| DB driver (Postgres) | `asyncpg` (via SQLAlchemy) | Fastest PG driver |
| AI agents | `pydantic-ai` | Typed deps, structured output |
| TUI | `textual` | Rich-based, CSS layout, widgets |
| Logging | `rich.logging.RichHandler` | Pretty; swap to `structlog` in prod |

## pyproject.toml: the one true config

For a new project, start with `uv init --app myproject`, then load `pyproject-strict.md` and adapt its strict defaults to the project rather than using a bundled scaffold.

## PEP 723: inline script metadata (mandatory for ALL scripts)

Every `.py` script; even throwaway; MUST use PEP 723 inline metadata with the `# ─── How to run ───` comment block. No venv, no `requirements.txt`. The script IS the environment spec. A script without the usage comment block is incomplete.

For a new script, write the PEP 723 metadata directly and use `uv run --script <script.py>`.

Load `one-liners.md` for full patterns, examples, and anti-patterns.

## Reference loading

Load on demand; not all at once.

| Need | Load |
|---|---|
| Full pyproject.toml config | `pyproject-strict.md` |
| Type patterns (NewType, Final, enums, narrowing) | `type-patterns.md` |
| Data modeling (container choice, frozen, parse-don't-validate) | `data-modeling.md` |
| Error handling (typed errors, union returns, exhaustive match) | `error-handling.md` |
| Async patterns (anyio) | `../../cookbook/async.md` |
| Data processing (polars / duckdb) | `data-processing.md` |
| FastAPI + SQLAlchemy stack | `fastapi-stack.md` |
| Library decision tree | `libraries.md` |
| **httpx2 optimization** (MUST load for any network code) | `httpx2-optimization.md` |
| **orjson** (when JSON is in the hot path; FastAPI/Pydantic v2 integration) | `orjson-stack.md` |
| One-liner scripts (PEP 723) | `one-liners.md` |
| PydanticAI agents | `pydantic-ai.md` |
| Textual TUI | `textual-tui.md` |

## httpx2: mandatory for ALL network requests

Every outgoing HTTP call MUST use [`httpx2`](https://github.com/pydantic/httpx2) (`httpx2[http2,brotli,zstd]`). Never `requests`, never `aiohttp`, never the original `httpx`.

**ALL optimizations are ON by default: not optional, not progressive, not "nice to have".** A bare `httpx2.AsyncClient()` is a bug; treat it like a lint violation. The correct way is the factory pattern in `httpx2-optimization.md` with: HTTP/2 enabled, tuned connection pool (200/40/30s), split timeouts (5/30/10/10), transport retries (3), TCP_NODELAY, follow_redirects, and event hooks for observability.

When writing or reviewing ANY network code, **ALWAYS load `httpx2-optimization.md`** and use the factory pattern verbatim. No exceptions.

## Quality verification

Run the project quality gates after every edit session:
- `uv run basedpyright`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

Fix every violation before declaring work done. basedpyright + ruff strict config catches the rest.

## In tests

Tests are strict too, with these exceptions (already configured in `pyproject.toml` per-file-ignores):

| In tests you may | Why |
|---|---|
| Use `assert` | That's how pytest works (`S101` ignored) |
| Use magic numbers | Test data (`PLR2004` ignored) |
| Access `_private` members | Testing internals (`SLF001` ignored) |
| Skip docstrings | Test names are the docs (`D` ignored) |
| Have unused function args | Fixtures (`ARG` ignored) |

Tests still follow the iron list; frozen dataclasses, typed errors, exhaustive match. If test fixtures need mutable state, explain the reason in the fixture class docstring.

## Existing codebases

When editing an existing file that doesn't follow these rules: **write new code in strict style, don't refactor existing code in the same change.** Mixing feature work with style migration makes reviews harder and bugs likelier.

## Activation

This skill activates whenever you are writing or modifying any `.py` file. Even one-off scripts get the strict treatment; that is the whole point of PEP 723 + uv: production hygiene with throwaway ergonomics.
