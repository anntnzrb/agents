---
description: Prefer modern Python syntax and stdlib patterns when compatible with the project's target Python version
condition:
  - "\\b(?:typing\\.)?(?:List|Dict|Tuple|Set|FrozenSet|Deque|DefaultDict|Counter|Optional|Union)\\b"
  - "\\bTypeAlias\\b|\\bTypeVar\\s*\\("
  - "\\{\\s*\\*\\*[^}]+,\\s*\\*\\*[^}]+\\}|\\b[a-zA-Z_][a-zA-Z0-9_]*\\s*=\\s*(?:len\\(|re\\.search\\(|[^\\n]+\\.search\\()"
  - "\\b(?:datetime\\.datetime\\.utcnow|datetime\\.datetime\\.utcfromtimestamp|os\\.path\\.|open\\([^\\n]*(?:\"r\"|'r')|\\.append\\s*\\(|dataclasses\\.(?:asdict|astuple)\\s*\\(|field\\s*\\([^\\n]*default\\s*=\\s*(?:\\[\\]|\\{\\}|set\\(\\)))"
scope:
  - text
  - tool
interruptMode: never
---

Use modern Python when it is compatible with the project's declared runtime.

First check the project's target version (`requires-python`, CI matrix, Docker image, pyright/ruff target version). Do not force syntax that the project cannot run.

Modernization preferences:
- Python 3.8+: use walrus `:=` when a value is assigned only to be immediately tested or reused in the condition.
  - Prefer `if match := pattern.search(text): ...` over `match = pattern.search(text); if match: ...`
  - Prefer `if (n := len(items)) > 0: ...` when `n` is useful in the guarded block.
  - Do not use walrus when it makes the expression clever or hides side effects.
- Prefer generator expressions for one-pass aggregation over materializing lists.
- Prefer comprehensions when they are simple transformations/filters. If the expression grows branches, side effects, or nested complexity, extract a named pure function.
- Prefer `sum`, `any`, `all`, `min`, `max`, `Counter`, `defaultdict`, `itertools`, and `operator` over hand-written imperative loops when they express the intent directly.
- Do not contort Python into point-free functional cosplay; readable Python wins.
- Python 3.9+: use built-in generics: `list[str]`, `dict[str, int]`, `tuple[A, B]`, `set[T]`.
- Python 3.9+: use `str.removeprefix()` / `str.removesuffix()` over manual slicing after `startswith()` / `endswith()`.
- Python 3.9+: use `dict_a | dict_b` / `dict_a |= dict_b` over `{**a, **b}` for dict merge/update.
- Python 3.10+: use `A | B` and `T | None` over `Union[A, B]` and `Optional[T]`.
- Python 3.10+: use `match` for real variant/destructuring logic; do not replace simple `if/elif` chains just to look modern.
- Python 3.10+: use parenthesized multi-context managers instead of backslash continuation or nested indentation.
- Python 3.11+: use `tomllib` for reading TOML.
- Python 3.11+: use `typing.Self` for fluent methods returning `self`.
- Python 3.12+: use `@typing.override` for intentional method overrides.
- Python 3.12+: use `type Alias = ...` and generic type parameter syntax (`def f[T](...)`) when the runtime target allows it.
- Python 3.12+: prefer improved f-string syntax over awkward escaping when target allows it.
- Python 3.12+: use `itertools.batched` instead of hand-written chunking.
- Python 3.13+: use `copy.replace` for copy-on-write updates when it matches the data model.
- Python 3.13+: use `warnings.deprecated` for explicit deprecation paths.
- Python 3.14+: use `uuid.uuid7()` for time-sortable IDs where chronological ordering is useful.
- Python 3.14+: use pathlib copy/move APIs when available and clearer.

General stdlib preferences:
- Prefer `pathlib.Path` over `os.path` string manipulation.
- Prefer timezone-aware datetimes (`datetime.now(UTC)`) over naive `utcnow()` / `utcfromtimestamp()`.
- Prefer context managers for files/resources.
- Prefer `collections.Counter`, `defaultdict`, `deque`, `heapq`, and `itertools` when they directly model the operation.
- Prefer `operator` functions over trivial lambdas in hot/simple functional code (`itemgetter`, `attrgetter`, `add`, `mul`).
- Avoid `dataclasses.asdict()` / `astuple()` in hot paths or when deep copy is not intended; use explicit projection or shallow field iteration.
- Prefer `field(default_factory=...)` for mutable dataclass defaults.

Use Ruff `UP`/pyupgrade to catch safe syntax modernizations, but respect configured target version.