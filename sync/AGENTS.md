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
- Generated wrappers call `python3 ~/.local/share/agents/sync-current/src/sync/cli.py launch <harness> -- ...`; launch performs a best-effort sync when the SSOT is available, then resolves and runs the cached npm binary.
- Runtime consumers must read installed state under `~/.local/share/agents/`, not files under the SSOT.
- Launch-time sync failures are warnings; cached harness launch remains available.
- Wrapper ownership is marker- and state-based. Stale generated wrappers are removed only when still owned; unmanaged conflicts are preserved.
- npm launch cache layout is `~/.cache/npm-tools/<tool>/packages/<package-key>/`, with version installs under `versions/<version>/` and package-local `current`/`previous` links.

## Validation

Run from repo root when sync code or tests change:

- `uv run --project sync sync --help`
- `cd ./sync && uv sync --frozen && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -n auto`
- `cd ./sync && uv run pytest tests/test_integration.py -q -o addopts=""`

## Stop Rules

- For docs-only edits, skip sync execution unless invocation behavior changed.
- Keep launch-wrapper behavior in this sync app; do not add a second launcher implementation in Rice.
