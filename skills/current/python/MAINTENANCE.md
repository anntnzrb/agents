# Python Skill Maintenance

Maintainer procedure, not loaded by `SKILL.md`. Run it when asked to refresh the Python skill against upstream sources, or once a year after a CPython feature release.

## Last run

- Date: 2026-10-01
- CPython checkout: `3.15` at 3.15.0rc2+dev (`021f634`); 3.15.0 final due the same day and treated as released
- Result: 3.15 idioms added to `cookbook/modern.md` as `(3.15+)` rules (`lazy import`, `frozendict`, `sentinel`, closed `TypedDict`, comprehension unpacking, UTF-8 default); pointers in `patterns-composition.md`, `patterns-iterators.md`, and `harnesses/omp/agent/rules/py-modern.md`. Skills stay at 3.14 and move to 3.15 one at a time when a 3.15 feature has a measured benefit (`docs/skills.md`); `market-hunter` moved first (`lazy from firecrawl`, `--help` 418 ms to 95 ms)

Update this section at the end of every run.

## Sources

Read upstream source, not memory. Vendored checkouts live at `~/src/vendored/<host>/<owner>/<repo>` and are read-only.

| Source | Checkout | Read |
| --- | --- | --- |
| CPython | `github.com/python/cpython` | `Doc/whatsnew/3.N.rst`, `Doc/deprecations/*.rst`, `Doc/deprecations/soft-deprecations.rst`, `Doc/library/`, `Doc/reference/`, `Doc/faq/`, `Doc/howto/` |
| AnyIO | `github.com/agronholm/anyio` | `docs/versionhistory.rst` |
| httpx2 | `github.com/pydantic/httpx2` | `src/httpx2/CHANGELOG.md` |
| basedpyright | `github.com/DetachHead/basedpyright` | release notes, `docs/configuration/config-files.md` |
| Ruff | `github.com/astral-sh/ruff` | `CHANGELOG.md` (rule renames, removals, new stable rules) |
| uv | `github.com/astral-sh/uv` | `CHANGELOG.md` (script metadata, `uv_build`, lock behavior) |

Refresh or create a checkout:

```bash
git -C ~/src/vendored/github.com/python/cpython pull --ff-only
git clone --depth 1 https://github.com/agronholm/anyio ~/src/vendored/github.com/agronholm/anyio
```

A checkout's `main` can be ahead of the latest release. Check `Include/patchlevel.h` (CPython) or tags, and treat unreleased versions as future.

## Stack decisions

Settled by the user on 2026-09-27. A refresh MUST NOT silently reverse them; if upstream evidence argues against one, report it and ask.

1. Type checker: basedpyright, `typeCheckingMode = "all"` for new projects; a repo's configured mode wins. mypy only where already in use
2. Lint and format: Ruff `select = ["ALL"]` with narrow justified ignores; `ruff format` only
3. Async: AnyIO for new code; raw `asyncio` only in inherited asyncio code; tests use AnyIO's pytest plugin
4. HTTP: `httpx2`; never `requests`, `aiohttp`, or `httpx`
5. `Any` banned in annotations (contain third-party `Any` at the boundary); `object` for genuinely unknown values, never where a Protocol, type parameter, union, or TypedDict fits
6. Variant dispatch: `match` plus `assert_never`
7. Broad `except Exception` only at boundaries, logged and re-raised or mapped, marked `# noqa: BLE001 - reason`
8. CLI: `typer` + `rich` for applications; `argparse` for zero-dependency scripts
9. Data: frozen slotted dataclasses; PEP 695 generics
10. Precedence: `SKILL.md` and `cookbook/modern.md` are policy; `references/advanced/` holds recipes that cannot contradict it; inherited projects keep their configured stack
11. No Python 2 compatibility code; `from __future__ import annotations` only below 3.14
12. uv, pytest, polars + duckdb, FastAPI + Pydantic v2, SQLAlchemy 2.x async

## Inclusion bar for `cookbook/modern.md`

- Include an idiom only when the language's own docs or semantics make it the better choice in essentially every program. Popularity is not evidence
- Cite the CPython doc path for each non-obvious claim
- Tag rules needing a newer runtime `(3.N+)` with the untagged fallback; untagged means the oldest supported target (currently 3.10)
- Reject niche features (free-threading, subinterpreters, codec modules, ID formats, DSL features) and cosmetic syntax
- Add unreleased-version features only after that version ships
- When the oldest supported target rises, delete fallbacks and tags that became universal

## Procedure

1. Refresh the checkouts above and record the versions.
2. Research with parallel read-only scouts, one per lens, each citing file:line:
   - New released `whatsnew` pages since the last run: universal idioms and behavior changes
   - `Doc/deprecations/` and soft deprecations: new Never rows, and removals that make existing rows obsolete
   - Audit every claim and example in `cookbook/modern.md`, `SKILL.md`, and `reference.md` against the docs
   - Stack changelogs (AnyIO, httpx2, basedpyright, Ruff, uv): renamed options, new defaults, deprecated APIs used in the skill
   - Contradiction sweep across `SKILL.md`, `cookbook/`, `references/`, and `harnesses/*/agent/rules/py-*.md`
   - Usage scan of `skills/current/*/` Python code for newly deprecated APIs
3. Read every scout report once all finish; verify each proposed change against the cited source yourself.
4. Apply changes with file-disjoint workers. `cookbook/modern.md` owns universal idioms and the Never table; other files point to it instead of restating.
5. Verify, then update "Last run".

## Verification

Run from the repository root:

```bash
uv run --script skills/current/skill-creator/scripts/cli.py quick-validate skills/current/python
git diff --check
rg -n '\x{2013}|\x{2014}' skills/current/python harnesses/omp/agent/rules
```

- Execute every changed snippet on the newest released interpreter with `-W error` (`uv run --no-project --python 3.N --with anyio --with httpx2 python file.py`); delete the throwaway files
- For every skill whose code changed, run `uv run --script skills/current/skill-creator/scripts/cli.py gates skills/current/<name> --tests` and its `--help`
- Follow the skill gate in `docs/skills.md`
