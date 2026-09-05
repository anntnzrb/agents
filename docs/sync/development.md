# Develop the sync application

The sync application is an isolated Python (uv) project under `sync/`. See [Repository layout](../repository-layout.md) for the module map. For the shared-skill workflow, see [Manage shared skills](../skills.md).

## Run sync from source

From the repository root, use the public entrypoint:

```bash
uv run --project sync sync
```

Keep `sync/src/sync/cli.py` as the public entrypoint. Do not add a `bin/` shell trampoline.

## Run the full checks

Run the static checks and the test suite from `sync/`:

```bash
cd sync
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -n auto
```

`uv run pytest -n auto` already includes `tests/test_integration.py`. Run the explicit single-process integration command when you are iterating on process-level behavior:

```bash
cd sync
uv run pytest tests/test_integration.py -q -o addopts=""
```

## Run a focused test

Pass the test file to pytest:

```bash
cd sync
uv run pytest tests/test_managed_tools.py
uv run pytest tests/test_wrappers.py
```

Add the narrowest regression test that covers the changed sync contract.

Add process-level integration coverage when a change creates a generated target or crosses a runtime boundary. Use harness names and paths as fixtures or adapter boundaries.

Keep tests of harness implementations and harness-local behavior beside their source under `harnesses/`.

## Write useful tests

- Test one behavior at the lowest layer that observes it. Do not repeat the same scenario in unit and process-level suites.
- Test shared code once, beside the shared module. Do not copy identical tests into every consumer; a consumer test covers only its own wiring.
- Assert observable behavior and contracts, not fixtures, mocks, or implementation details.
- Add a test only when it can fail on a real regression. Delete tests that duplicate coverage or re-prove what another test already covers.
- Keep skill and harness tests beside their owning source. `sync/tests/` covers sync behavior only.

## Change sync behavior

1. Find the owning module under `sync/src/sync/`.
2. Add or update the focused test.
3. Make the smallest implementation change.
4. Run the focused test.
5. Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, and `uv run pytest -n auto`.
6. Run `git diff --check` from the repository root.
7. Update the related page under `docs/sync/` when the change affects commands, paths, lifecycle, platforms, or generated behavior.

Keep these contracts intact:

- Keep `sync/src/sync/cli.py` as the public entrypoint.
- Keep wrapper generation inside the sync application.
- Validate external files and network data at their boundary.
- Keep filesystem operations safe to retry.
- Preserve unmanaged files unless recorded ownership permits cleanup.

## Change harness configuration

1. Edit the matching source under `harnesses/`.
2. Run `uv run --project sync sync` from the repository root.
3. Inspect the generated root derived from the adapter's `homeSegments` and `runtimeSubdir` fields.
4. Run the wrapper with `--version`.

Keep harness-specific tests and documentation beside the owning source under `harnesses/`. Do not place them in `sync/tests/` or `docs/`.

Do not edit a generated harness home. Sync replaces managed files on the next run.

## Add a harness adapter

1. Add the adapter to `sync/src/sync/core/harness_adapters.py`.
2. Add its source directory under `harnesses/<harness>/`.
3. Add wrapper tests for every supported platform.
4. Add integration coverage for generated files and hooks.
5. Run the full checks.
6. Update the [Harness adapter reference](harnesses.md) only when the adapter changes the shared workflow or requires a harness-specific user action.

Store launcher metadata in the adapter. Do not repeat package names, target homes, or hook rules in user configuration.

Do not add a supported-harness roster to the documentation. `HARNESS_ADAPTERS` owns that list.

## Parsing and format contracts

Sync parses configuration, secrets, environment files, and extension/skill sources across several formats. All implementations must uphold these parsing contracts:

### JavaScript and TypeScript import extraction

- **Static and dynamic imports**: Extracts static ESM `import` statements, `export ... from` re-exports, dynamic `import()` expressions, and CommonJS `require()` calls.
- **Require normalization**: `require("...")` calls are normalized so the scanner recognizes them as dynamic imports during AST traversal.
- **Comment and string immunity**: Import and require statements inside single-line comments (`//`), multiline block comments (`/* ... */`), string literals (single or double quotes), and template literals (`` `...` ``) are ignored.
- **Type-only erasure**: Type-only imports (`import type { ... }`) are stripped during transpilation/scanning and excluded from runtime dependency specifiers.
- **Specifier classification**: Downstream package validation (`missing_package_roots`) ignores relative paths (`.`, `./*`, `../*`), builtin modules (`node:*`, `bun:*`, `bun`), and `data:` URIs, validating only unresolved npm package roots and scoped package identifiers.

### Python scanner note

The Python implementation (`sync/src/sync/packages/validate.py`) performs import scanning with a comment/string-stripping state machine plus targeted patterns instead of a full JS/TS AST library. Any change to the scanner must preserve comment/string immunity: add adversarial cases (comments, multiline strings, template literals, type-only imports) to `sync/tests/test_package_validate.py`.

### JSON with Comments (JSONC)

- **Comment tolerance**: Accepts single-line (`//`) and multiline (`/* ... */`) comments across configuration files, manifests, and local secrets (`secrets.local.json`, `deployment.json`, `release-manifest.json`, hook states, wrapper state).
- **Trailing comma tolerance**: Permits trailing commas in objects and arrays.

### YAML

- **Standard YAML mappings**: Parses and emits standard YAML configuration templates (e.g., CLIProxyAPI `config.yaml.tmpl`).
- **Credential pool expansion**: Expands declared `x-credential-pool` markers into native credential profiles and compatibility provider blocks, merging shared profile attributes while enforcing pool reference completeness.

### Dotenv (`.env`)

- **Variable expansion disabled**: Literal `$VAR` or `${VAR}` sequences remain unexpanded (`expandVariables: false`).
- **Empty key omission**: Keys with empty or unset values are omitted from the decoded environment map (`preserveEmptyStrings: false`).

### Python scanner note

The Python implementation (`src/sync/packages/validate.py`) performs import scanning with a comment/string-stripping state machine plus targeted patterns instead of a full JS/TS AST library. Any change to the scanner must preserve comment/string immunity: add adversarial cases (comments, multiline strings, template literals, type-only imports) to `tests/test_package_validate.py`.

## Behavioral contract

The integration test suite (`sync/tests/test_integration.py`) serves as the executable black-box specification for the sync system. Rather than testing internals, these scenarios assert observable system boundaries.

Sync is compliant if and only if it satisfies all of the following black-box behavioral contracts:

### 1. CLI syntax, help modes, and standard exit codes

- **`0` (Success & Graceful Skip)**: Returned on successful synchronization, help inspection flags (`--help`, `-h`, `help`, `sync --help`, `launch --help`), and when a concurrent run gracefully skips due to lock contention.
- **`1` (Runtime & Validation Failure)**: Returned on missing SSOT runtime source directories, invalid configuration schemas, unparseable deployment configurations, or hook execution failures.
- **`2` (CLI Syntax Error)**: Returned when unrecognized commands, flags, or invalid argument separator syntax are passed (e.g., `sync launch` with no target, or `sync launch codex missing-separator`).
- **`124` (Timeout)**: Returned when sync execution or launcher processes exceed configured deadlines.
- **`127` (Missing Command / Missing Runtime)**: Returned when an unmanaged or missing command is executed, or when a generated launcher wrapper is invoked without a valid sync runtime.

### 2. Missing source vs. malformed configuration

- **Missing SSOT source tree**: When `.config/agents/sync` (or required source manifests) is absent or unreadable, sync fails fast with exit code `1` and emits a descriptive diagnostic to stderr (`missing or unreadable runtime source`).
- **Malformed configuration**: When structured configuration files (such as `.config/agents/tools/cliproxyapi/deployment.json` or hook manifests) contain invalid JSON/YAML or fail schema decoding, sync fails with exit code `1` and logs a parse error identifying the offending file.

### 3. Owned entry cleanup vs. unmanaged file preservation

- **Pruning stale owned entries**: Stale managed files (entries recorded in previous state files or declared in harness adapters but removed from current SSOT) are automatically removed upon synchronization.
- **Preserving unmanaged user files**: Files placed in harness homes or tool directories by users (e.g., `~/.omp/agent/logs/user.log`, `~/.local/bin/my-script`) that were never managed by sync are strictly preserved.
- **Unmanaged wrapper conflicts**: If an unmanaged file already exists at a desired wrapper path (e.g., `~/.local/bin/codex`), sync preserves the unmanaged binary without overwriting it, records the conflict, and emits a warning on stderr (`preserving unmanaged wrapper conflict`).

### 4. Repeated reconciliation and within-run idempotency

- Successive sync runs against an unchanged source of truth must produce identical filesystem state.
- Idempotent runs must not touch, rewrite, or churn existing matching files: destination file inode numbers (`ino`) and modification timestamps (`mtime`) must remain stable.

### 5. Transactional publication and failure recovery

- When publishing endpoint configurations or rendered templates, sync verifies client endpoint readiness before modifying active harness configuration files.
- If target endpoints are unreachable, existing files are preserved without partial overwrites or corruption.
- In the event of a mid-publication failure, modified targets are rolled back to their pre-publication snapshots.
- Once underlying failures are resolved, subsequent sync runs cleanly reconcile and publish all managed targets.

### 6. Process lock contention and release

- An exclusive non-blocking POSIX lock (`flock(LOCK_EX | LOCK_NB)` on `~/.local/share/agents/sync-managed/sync.lock`) guards synchronization.
- If another sync process currently holds the lock, incoming runs exit cleanly with code `0` and write `another sync is already running; skipping` to stderr.
- When the lock holder exits or terminates, the lock is immediately released and available for subsequent processes.

### 7. Cached launch fallback and offline resilience

- When invoking `sync launch <tool> [-- <args...>]`, the launcher attempts to resolve and stage packages from the registry.
- If the remote package registry is unreachable or offline, the launcher falls back to the locally cached package (`~/.cache/npm-tools/<tool>/packages/<key>/current`), emits a diagnostic warning to stderr (`using cached <tool>@<version>`), and executes the cached executable with all forwarded arguments.

### 8. Wrapper runtime isolation and diagnostic hints

- Generated launch wrappers in `~/.local/bin/<harness>` delegate execution to the managed sync runtime (`~/.local/share/agents/sync-current/src/sync/cli.py`).
- If the sync runtime is missing or removed, invoking the wrapper must immediately exit with status code `127` and output `agents: sync runtime is missing; run sync from the agents repository` to stderr.

### 9. Environment variable precedence cascade

Subprocess environments during launch are resolved according to strict hierarchical precedence:
1. **Base defaults**: Loaded from `.config/agents/.env` in the SSOT.
2. **Parent process environment**: Overrides values from `.env`.
3. **Adapter overrides**: Configured in adapter launcher specifications (`harness.launcher.env`), taking precedence over both parent process environment and `.env`.
