# AGENTS.md

This is the isolated sync application.

## Scope

- `./pyproject.toml`: sync app metadata, dependencies, and tool config (ruff, pyright, pytest)
- `./uv.lock`: sync app lockfile
- `./src/sync/`: application code
- `./tests/`: sync-specific tests (plus `tests/golden/` frozen behavior fixtures)
- `../docs/sync/`: sync application documentation

## Contracts

- Keep behavior changes deliberate.
- Public callable entrypoint is `src/sync/cli.py` (console script `sync`); wrappers/tooling invoke it via `uv run --project sync sync` from the repo root or `uv run sync` from `sync/`.
- Sync supports macOS and Linux only.
- A supported `../harnesses/<harness>/` directory opts into that harness; `src/sync/core/harness_adapters.py` owns internal launch and sync metadata.
- Use absolute imports (`from sync.core...`) across package boundaries.
- Sync owns generated launch wrappers under `~/.local/bin` and assumes that directory is on `PATH`.

## Managed Tool Contract

- Managed release manifests live under `../tools/cliproxyapi/` and pin every supported platform asset by SHA-256.
- Sync downloads only pinned official release assets and caches verified executables under `~/.cache/github-tools` by default.
- Managed tool wrappers use the upstream executable name and pass generated configuration explicitly.
- Sync does not install or control system services.

## Model Catalog Contract

- The normalized model catalog and its cache are harness-agnostic.
- Prefer each harness's native remote-model discovery over generated per-harness catalogs.
- Do not add per-harness model serializers or a per-harness materialization layer under `src/sync/`.
- Live provider catalogs decide availability; models.dev supplies metadata and protocol hints.

## Launch Wrapper Contract

- A manual sync creates or reconciles wrappers before returning.
- Sync installs its runtime under `~/.local/share/agents/sync-releases/<releaseId>/` with a `sync-current` symlink to the latest release.
- Generated wrappers call `~/.local/share/agents/sync-current/.venv/bin/python -m sync.cli launch <harness> -- ...`; launch performs a best-effort sync when the SSOT is available, then resolves and runs the cached npm binary.
- Runtime consumers must read installed state under `~/.local/share/agents/`, not files under the SSOT.
- Launch-time sync failures are warnings; cached harness launch remains available.
- Wrapper ownership is marker- and state-based. Stale generated wrappers are removed only when still owned; unmanaged conflicts are preserved.
- npm launch cache layout is `~/.cache/npm-tools/<tool>/packages/<package-key>/`, with version installs under `versions/<version>/` and package-local `current`/`previous` links.

## Validation

Sync contributor gates are enforced via Python/uv tooling and automated git hooks (`pre-commit` and `pre-push`). Git hooks never rewrite tracked source files and run under POSIX `sh` with `set -eu`. Every hook invocation reconciles dependencies with `uv sync --frozen` before executing gates with `--no-sync`.

### Validation Commands

From repo root:
- Quick CLI smoke test: `uv run --project sync sync --help`
- Run all sync gates: `(cd sync && uv sync --frozen && uv run --no-sync ruff check . && uv run --no-sync ruff format --check . && uv run --no-sync pyright && uv run --no-sync pytest -n auto)`

From `sync/` directory:
- Bootstrap/reconcile venv: `uv sync --frozen`
- Lint: `uv run --no-sync ruff check .`
- Format check: `uv run --no-sync ruff format --check .`
- Type check: `uv run --no-sync pyright`
- Test suite: `uv run --no-sync pytest -n auto`
- All-in-one gate: `uv sync --frozen && uv run --no-sync ruff check . && uv run --no-sync ruff format --check . && uv run --no-sync pyright && uv run --no-sync pytest -n auto`

### Hook Contracts

- **`pre-commit`**: Runs `git diff --cached --check`, then changes into `sync/` and executes `uv sync --frozen`, `uv run --no-sync ruff check .`, `uv run --no-sync ruff format --check .`, and `uv run --no-sync pyright`.
- **`pre-push`**: Executes the same Python gates (`uv sync --frozen`, Ruff lint/format check, Pyright) followed by `uv run --no-sync pytest -n auto`. No separate duplicate integration run is needed because `pytest -n auto` covers the full suite including integration tests.

### Code Quality and Typing Policies

- Use strict typing; validate external data at boundaries and avoid `Any`.
- Keep lint, formatting, and type checks clean using the committed configuration in `pyproject.toml`.
- Fix underlying problems rather than weakening gates or adding unjustified suppressions.
- Use TDD for behavior changes; keep tests deterministic, isolated, and focused on observable contracts.

## Stop Rules

- For docs-only edits, skip sync execution unless invocation behavior changed.
- Keep launch-wrapper behavior in this sync app; do not add a second launcher implementation in Rice.
