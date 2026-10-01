---
description: Prefer modern Python syntax and stdlib patterns when compatible with the project's target Python version
condition:
  - "\\b(?:typing\\.)?(?:List|Dict|Tuple|Set|FrozenSet|Deque|DefaultDict|Counter|Optional|Union)\\b"
  - "\\bTypeAlias\\b|\\bTypeVar\\s*\\(|\\bGeneric\\s*\\[|\\b(?:click|fire)\\b"
  - "\\{\\s*\\*\\*[^}]+,\\s*\\*\\*[^}]+\\}|\\b[a-zA-Z_][a-zA-Z0-9_]*\\s*=\\s*(?:len\\(|re\\.search\\(|[^\\n]+\\.search\\()"
  - "\\b(?:datetime\\.datetime\\.utcnow|datetime\\.datetime\\.utcfromtimestamp|os\\.path\\.|open\\([^\\n]*(?:\"r\"|'r')|\\.append\\s*\\(|dataclasses\\.(?:asdict|astuple)\\s*\\(|field\\s*\\([^\\n]*default\\s*=\\s*(?:\\[\\]|\\{\\}|set\\(\\)))"
scope:
  - tool:edit(*.py)
  - tool:edit(**/*.py)
  - tool:write(*.py)
  - tool:write(**/*.py)
interruptMode: never
---

Follow `skill://python/cookbook/modern.md` as the authoritative policy for universal Python idioms and its Never table.

Check the project's target version first (`requires-python`, CI matrix, Docker image, `basedpyright` and Ruff `target-version`). Do not use syntax the target runtime cannot execute.

Core idioms summary (see `cookbook/modern.md` for full rules and examples):

- Iteration and collections: build collections with comprehensions over `.append` loops; pass generator expressions straight to `sum`, `any`, `all`, and `min`/`max` (with `default=`); use `zip(..., strict=True)`; merge dicts with `a | b` and `a |= b` instead of `{**a, **b}`; use `itertools.pairwise` and `itertools.batched` (3.12+, `strict=True` on 3.13+); flatten with `[*xs for xs in groups]` (3.15+); prefer `operator.attrgetter`/`itemgetter` over trivial lambdas; use `:=` only when it removes a repeated call.
- Strings and I/O: use f-strings and `"".join(parts)`; strip affixes with `str.removeprefix()` and `str.removesuffix()`; group context managers in parenthesized `with (...)`; use `pathlib.Path` with `encoding="utf-8"` on text opens (`Path.copy`/`move` on 3.14+); read TOML with `tomllib` (3.11+); use timezone-aware `datetime.now(UTC)` and `uuid.uuid7()` (3.14+); defer heavy imports with module-level `lazy import` (3.15+) instead of function-body imports.
- Data and typing: default to `@dataclass(frozen=True, slots=True)` (`field(default_factory=...)` for mutable defaults, `copy.replace` on 3.13+); use `enum.StrEnum` (3.11+); use `frozendict` for constant mappings and `sentinel("NAME")` for missing-argument markers (3.15+); use builtin generics (`list[T]`, `dict[K, V]`), `collections.abc` input protocols, and `X | None` unions; use PEP 695 `def f[T]`, `class Box[T]`, and `type Alias = ...` on 3.12+ (never `TypeVar`, `Generic`, `TypeAlias`, `Optional`, `Union`, `List`, or `Dict`); use `Self` (3.11+), `@override` (3.12+), `TypeIs[T]` (3.13+), `@warnings.deprecated` (3.13+), and `TypedDict` with `closed=True` (3.15+); end variant `match` blocks with `case _ as unreachable: assert_never(unreachable)`; omit `from __future__ import annotations` on 3.14+ and keep it below 3.14 where annotations need deferral.
- Stack and tooling defaults: use `anyio` for async, `httpx2` (`httpx2[http2,brotli,zstd]`) for HTTP, `typer` + `rich` for multi-command CLIs, and stdlib `argparse` for zero-dependency single-file scripts (including skill `scripts/cli.py` entrypoints; never `click` or `fire`). Enforce modernizations with Ruff `select = ["ALL"]` and narrow justified ignores.
