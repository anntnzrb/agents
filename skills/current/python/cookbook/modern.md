# Modern Python: Baseline Idioms and Prohibitions

Mandatory for every Python task. Each rule follows from the language's own semantics, not popularity. Cited paths are in the CPython `Doc/` tree.

Untagged rules work on 3.10+. A `(3.N+)` tag needs `requires-python >= 3.N`; below that, follow the untagged fallback or skip the rule.

## Contents

- Iteration and collections
- Strings
- Data modeling
- Functions and typing
- Errors
- Resources, I/O, and processes
- Async
- Never

## Iteration and collections

- Build collections with comprehensions, not an empty container plus `.append` in a loop. Comprehensions are inlined into the caller's frame (3.12+, `whatsnew/3.12.rst` PEP 709)
- Feed generator expressions straight into reductions; give `min`/`max` a `default=` when the input can be empty. `any`/`all` short-circuit (`builtins/functions.rst`)
- Iterate directly; use `enumerate(xs)` when you need the index and `d.items()` when you need the value
- Pass `strict=True` to `zip` whenever the inputs must have equal length; plain `zip` silently truncates (`builtins/functions.rst` "possibly manifesting as a hard-to-find bug")
- Count with `Counter`, group with `defaultdict(list)`, read optional keys with `d.get(k, default)`
- Merge mappings into a new dict with `a | b`; update in place with `a |= b`
- Destructure with star unpacking instead of index arithmetic
- Consecutive pairs: `itertools.pairwise`. Fixed-size chunks: `itertools.batched(xs, n)` (3.12+), with `strict=True` when a short final chunk is invalid (3.13+)
- Flatten one level with unpacking in a comprehension: `[*xs for xs in groups]`, `{**d for d in layers}` (3.15+, PEP 798); below 3.15, `itertools.chain.from_iterable(groups)`
- Sort and select with `key=`; prefer `operator.attrgetter`/`itemgetter` over trivial lambdas ("simpler and faster", `howto/sorting.rst`)
- Bind a value once with `:=` only when it removes a repeated call

```python
totals = {user.id: sum(o.amount for o in user.orders) for user in users}
latest = max((e.created_at for e in events), default=None)
for name, score in zip(names, scores, strict=True):
    ranking[name] = score
by_team = defaultdict(list)
for member in members:
    by_team[member.team].append(member)
config = defaults | overrides
head, *rest = parts
deltas = [b - a for a, b in pairwise(timestamps)]
ranked = sorted(players, key=attrgetter("rating"), reverse=True)
if match := PATTERN.search(line):
    handle(match)
```

## Strings

- Format with f-strings; `f"{expr=}"` prints the expression text and its `repr` for debug output
- Build large strings with `"".join(parts)`; strings are immutable, so `+=` in a loop copies repeatedly (`faq/programming.rst`)
- Strip an exact affix with `removeprefix`/`removesuffix`. `lstrip`/`rstrip` strip a character set: `"Arthur: three!".lstrip("Arthur: ") == "ee!"` (`builtins/stdtypes.rst`)
- On 3.12+, f-string expressions may reuse the outer quote and contain backslashes (PEP 701)

```python
token = header.removeprefix("Bearer ")
report = "\n".join(f"{row.name}: {row.total:,.2f}" for row in rows)
```

## Data modeling

- Records are `@dataclass(frozen=True, slots=True)`; add `kw_only=True` once a constructor has several fields or defaults
- Closed string domains are `enum.StrEnum` with `auto()` (3.11+): members are real `str`, so they serialize and compare as strings
- Update immutable records with `copy.replace(obj, field=value)` (3.13+); below 3.13, `dataclasses.replace`
- Money and other exact decimals use `decimal.Decimal` or integer minor units, never `float` (`faq/design.rst`); decode JSON with `json.loads(raw, parse_float=Decimal)`
- Timestamps are timezone-aware: `datetime.now(UTC)` (3.11+; `timezone.utc` below)
- Parse TOML with stdlib `tomllib` in binary mode (3.11+)
- Constant lookup tables are `frozendict` (3.15+, `builtins/functions.rst`): `Final` only blocks rebinding the name, while `frozendict` rejects item assignment, is hashable, and serializes with `json`. Below 3.15, wrap the dict in `types.MappingProxyType`
- Missing-argument markers are `MISSING = sentinel("MISSING")` (3.15+, PEP 661): it has a readable repr, keeps its identity through `copy` and through `pickle` when defined at module scope under its own name, and types as `int | MISSING`. Below 3.15, `MISSING = object()`

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Endpoint:
    host: str
    port: int = 443
    scheme: Scheme = Scheme.HTTPS

secure = replace(endpoint, port=8443)
```

## Functions and typing

- Use builtin generics (`list[int]`, `dict[str, T]`), `collections.abc` protocols for inputs (`Iterable`, `Sequence`, `Mapping`, `Callable`), and `X | None` / `A | B` unions
- Declare generics and aliases with PEP 695 syntax (3.12+): `def first[T](xs: Sequence[T]) -> T`, `class Box[T]:`, `type Json = ...`. No module-level `TypeVar`, `typing.Generic` subscripting, or `TypeAlias` (deprecated 3.12, `library/typing.rst`). `type` aliases are lazy, so recursive aliases need no quotes
- Return `Self` from fluent methods, `__enter__`, and alternative constructors (3.11+)
- Mark every overriding method with `@override` (3.12+) so a renamed base method becomes a type error
- Narrowing predicates return `TypeIs[T]` (3.13+), which also narrows the negative branch; `TypeGuard` does not
- Dispatch on closed unions with `match`, ending in `case _ as unreachable: assert_never(unreachable)` (3.11+). Match constants with dotted names (`case Color.RED:`); a bare name is a capture pattern that always matches (`reference/compound_stmts.rst`)
- Declare `TypedDict` payloads `closed=True` when an unknown key is a bug, or `extra_items=T` when extra keys are allowed but typed (3.15+, PEP 728, `library/typing.rst`)
- Make parameters keyword-only with `*` when positional order is not self-evident; use `/` only for parameters whose names carry no meaning
- Deprecate APIs with `@warnings.deprecated` (3.13+) so type checkers flag callers too
- On 3.14+, write forward references unquoted and drop `from __future__ import annotations` (deprecated in 3.14, `whatsnew/3.14.rst`). Below 3.14, keep it where annotations need deferral. Read runtime annotations with `annotationlib.get_annotations` (3.14+)

```python
type Json = bool | int | float | str | None | list[Json] | dict[str, Json]

def first[T](items: Sequence[T]) -> T:
    return items[0]

match shape:
    case Circle(radius=r):
        area = pi * r * r
    case Square(side=s):
        area = s * s
    case _ as unreachable:
        assert_never(unreachable)
```

## Errors

- Catch the narrowest exception the layer can act on. Custom exceptions subclass `Exception`, never `BaseException`
- EAFP on the expected path: since 3.11, `try` costs nothing when no exception is raised (`whatsnew/3.11.rst` zero-cost exceptions), and a pre-check races with the real operation
- Re-raise the active exception with bare `raise`; translate with `raise NewError(...) from err`, or `from None` to deliberately hide the cause
- Add context without changing the type: `err.add_note(...)` then `raise` (3.11+)
- Handle `ExceptionGroup` with `except*` (3.11+)
- Validate with explicit `raise`; `assert` is removed under `-O` (`reference/simple_stmts.rst`)
- Catch broad `Exception` only at process, request, or task boundaries to log and re-raise or map; mark with `# noqa: BLE001 - <reason>`

```python
try:
    record = cache[key]
except KeyError as err:
    raise RecordNotFound(key) from err

try:
    process(item)
except ValueError as err:
    err.add_note(f"while processing {item.id=}")
    raise
except Exception as err:  # noqa: BLE001 - boundary catch to map error
    raise ProcessError(f"failed to process {item.id=}") from err
```

## Resources, I/O, and processes

- Own every file, lock, socket, and client with `with`; group several in one parenthesized `with (...)`
- Paths are `pathlib.Path` with `/`; read and write through `read_text`/`write_text`/`open`. On 3.14+, `Path.copy`/`copy_into`/`move`/`move_into` replace `shutil` for path objects (`copy` is always recursive)
- Pass `encoding="utf-8"` to every text-mode open. Before 3.15 the default is the locale encoding (`library/io.rst`, PEP 597 `EncodingWarning`); 3.15 defaults to UTF-8, but `whatsnew/3.15.rst` still recommends an explicit `encoding` for code that runs on several versions
- Run commands as argument lists with `check=True`: `subprocess.run(["git", "log", ref], check=True, capture_output=True, text=True)`
- Log with lazy `%` arguments, `logger.info("sent %s in %d ms", msg_id, ms)`: formatting is deferred until a handler emits the record (`howto/logging.rst` Optimization)
- Defer heavy imports with module-level `lazy import x` / `lazy from x import y` (3.15+, PEP 810) instead of imports inside function bodies. A failed lazy import raises at first use, so keep an import eager when its failure must be caught at startup. `lazy` is a `SyntaxError` inside functions, classes, and `try` blocks, and with `*` or `__future__` imports (`whatsnew/3.15.rst`)

```python
with (
    src_path.open(encoding="utf-8") as src,
    dst_path.open("w", encoding="utf-8") as dst,
):
    dst.writelines(transform(line) for line in src)
```

## Async

- Run concurrent work in `anyio.create_task_group()`: a failing child cancels siblings and every task is awaited before the block exits. Never untracked background tasks
- Bound waits with `with anyio.fail_after(seconds):` or `with anyio.move_on_after(seconds):`
- Start programs with `anyio.run(main)`; raw `asyncio` is reserved for inherited code or library callbacks
- Move unavoidable blocking calls off the event loop with `await anyio.to_thread.run_sync(fn, ...)`

```python
import anyio

async def worker(name: str, out: dict[str, int]) -> None:
    await anyio.sleep(0.01)
    out[name] = len(name)

async def main() -> None:
    results: dict[str, int] = {}
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(worker, "users", results)
            tg.start_soon(worker, "orders", results)
    total = await anyio.to_thread.run_sync(sum, results.values())
    assert total == 11

anyio.run(main)
```

## Never

| Never | Instead | Why |
| --- | --- | --- |
| `def f(xs=[])` or any mutable default | `xs: list[T] \| None = None`, or `field(default_factory=list)` | Defaults evaluate once, at definition time (`faq/programming.rst`) |
| `lambda: i` capturing a loop variable | Bind it: `lambda i=i: i`, or `functools.partial` | Closures read the variable at call time, so all see the last value |
| `x is 200`, `name is "admin"` | `==` | Identity of equal ints and strings is an implementation detail; 3.8+ warns |
| `x == None`, `flag == True` | `x is None`, `if flag:` | `==` calls an overridable `__eq__` |
| `type(x) == T` | `isinstance(x, T)` or `match` | Breaks subclasses and ABCs |
| `if len(xs) == 0:` | `if not xs:` | Containers define truthiness |
| `for i in range(len(xs)):` | `for x in xs` / `enumerate(xs)` | Indexing is slower and fails on plain iterables |
| `k in d.keys()`, `for k in d: d[k]` | `k in d`, `d.items()` | Extra view object or second lookup |
| `sum([f(x) for x in xs])` | `sum(f(x) for x in xs)` | Builds a throwaway list |
| `s += piece` in a loop | `"".join(pieces)` | Repeated copying |
| `s.lstrip("prefix")` for an affix | `s.removeprefix("prefix")` | Strips characters, not a substring |
| Mutating a list or dict while iterating it | Build a new one, or iterate `list(d)` | Skips items or raises `RuntimeError` |
| Bare `except:`, `except BaseException:`, `except Exception: pass` | Specific exceptions; boundary catch marked `# noqa: BLE001 - <reason>` that logs and re-raises or maps | Traps `KeyboardInterrupt`/`SystemExit`, hides bugs |
| `raise err` to re-raise | `raise` | Adds the current frame to the traceback |
| Raising inside `except` without `from` | `raise New(...) from err` | Chains with a misleading "during handling" message |
| `return`/`break`/`continue` in `finally` | Move it after the `try` statement | Discards the in-flight exception; `SyntaxWarning` in 3.14+ (PEP 765) |
| `assert` to validate input or state | `if ...: raise ValueError(...)` | Stripped under `-O` |
| `eval`/`exec` on data | `json`, `tomllib`, `ast.literal_eval` | Arbitrary code execution |
| `shell=True` with interpolated input | Argument list | Shell injection |
| `open(...)` outside `with`, or text mode without `encoding=` | `with path.open(encoding="utf-8")` | Leaked handles; locale-dependent decoding |
| `os.path` string manipulation | `pathlib.Path` | Separator and edge-case bugs |
| Naive `datetime.now()` / `utcnow()` | `datetime.now(UTC)` | Naive values compare and subtract wrongly |
| `float` for money | `Decimal` or integer cents | Binary floats cannot represent decimal fractions |
| f-strings or `%`/`.format` inside logging calls | `logger.info("x=%s", x)` | Formats even when the level is disabled |
| `global` for shared state | Pass arguments or own state in an object | Hidden coupling, untestable |
| `from module import *` | Explicit imports | Shadows names, blinds type checkers |
| Python 2 compatibility: `six`, `u""`, `class X(object)`, `super(Cls, self)`, coding cookies, `__future__` imports other than `annotations` | Python 3 forms | Dead since 3.0 |
| `typing.Optional`/`Union`/`List`/`Dict`/`Tuple`/`Callable`/`Sequence`, `TypeAlias`, module-level `TypeVar` on 3.12+ | `X \| None`, builtins, `collections.abc`, PEP 695 | Deprecated aliases (`library/typing.rst`) |
| In inherited asyncio code: `asyncio.get_event_loop()` outside a running loop, `asyncio.iscoroutinefunction`, event loop policies | `asyncio.run`, `get_running_loop()`, `inspect.iscoroutinefunction`, `asyncio.run(..., loop_factory=)` | Deprecated; removed in 3.16 (`deprecations/`) |
| `Any` in annotations | Contain third-party `Any` at the boundary; narrow immediately with `isinstance` or `match` | Disables checking for everything it touches |
| `object` where the shape is known | `Protocol`, a PEP 695 type parameter, a union, or `TypedDict`; keep `object` for genuinely unknown values | `object` exposes no attributes, so callers must narrow what the type could have stated |
| Invented noqa codes (`BROAD_EXCEPT_OK`, `OBJECT_OK`) | Real Ruff codes with a reason: `# noqa: BLE001 - <reason>` | Ruff does not recognize them, so they suppress nothing and document nothing |
| `requests`, `aiohttp`, or `httpx` in new code | `httpx2` | Stack policy (`SKILL.md` Stack); inherited code keeps its client until migrated |
| `shutil.rmtree(onerror=)`, `tarfile` extraction without `filter="data"`, `os.path.commonprefix` for paths | `onexc=`, `filter="data"`, `os.path.commonpath` | Deprecated or unsafe (`deprecations/`) |
