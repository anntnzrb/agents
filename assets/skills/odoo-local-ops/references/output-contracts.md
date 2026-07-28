# Output Contracts

The CLI is JSON-first with text fallback.

Use `--json` whenever another tool or agent will consume the result. Text output is for quick human inspection only.

## Core conventions

Current command output is command-shaped, not wrapped in a generic envelope.

Principles:

- successful commands return only the data needed for that command
- expected absences stay explicit as `null`, empty lists, or empty counts
- errors are actionable and do not leak secrets
- secret values from `odoo.conf`, `.env`, or environment are never emitted raw

## Error shape

Failures are machine-readable enough for agent use.

```json
{
  "error": "psql executable not found; use --psql, run from the Odoo install tree, or configure pg_path",
  "checked": [
    "C:\\path\\nearby\\PostgreSQL\\bin\\psql.exe",
    "PATH lookup via psql"
  ]
}
```

Notes:

- `error` is always the primary message
- `checked` appears when executable/path/runtime discovery matters
- command exits non-zero on failure
- read-only SQL rejection also uses the same `error` field

## Success shapes by command family

### `env inspect`

Top-level keys:

- `runtime`
- `root`
- `config_path`
- `config`
- `addons_paths`
- `effective_db_name`
- `psql`

Compose example:

```json
{
  "runtime": {
    "backend": "compose",
    "root": "<odoo-runtime>",
    "config_path": "<odoo-runtime>/config/odoo.conf",
    "compose_command": "/usr/local/bin/docker compose",
    "env": {
      "POSTGRES_PASSWORD": "<redacted>"
    }
  },
  "root": "<odoo-runtime>",
  "config_path": "<odoo-runtime>/config/odoo.conf",
  "config": {
    "db_host": "db",
    "db_port": "5432",
    "db_user": "odoo",
    "db_name": "etech"
  },
  "addons_paths": [
    "<odoo-runtime>/source/<odoo-version>/odoo/addons",
    "<custom-addons>/addons"
  ],
  "effective_db_name": "etech",
  "psql": {
    "path": "docker-compose:db/psql",
    "checked": ["Docker Compose service db"]
  }
}
```

Host-runtime output has the same shape but `runtime.backend` is `windows-host` and `psql.path` is a host executable.

`config` and runtime env are redacted automatically for secret-like keys.

### `addons list`

Top-level keys:

- `count`
- `modules`

Each entry currently includes:

- `module`
- `path`
- `addons_dir`

### `addons manifest <module>`

Top-level keys:

- `module`
- `path`
- `manifest`

`manifest` is literal manifest data parsed from `__manifest__.py`. Treat it as filesystem metadata, not proof of install state.

### `module status|models|tables|m2m|fks`

Current DB-backed commands return the PostgreSQL helper payload directly, or a small module wrapper plus DB rows.

Common DB payload keys:

- `database`
- `runtime`
- `rows`
- `row_count`
- `psql`
- `checked`
- `stdout`

Notes:

- `rows` is canonical parsed result
- `row_count` reflects parsed CSV rows
- `psql` reports host executable or Compose service path
- `checked` shows discovery attempts
- `stdout` is raw CSV traceability, not the main contract

`module status` additionally includes:

- `module`
- `path`
- `manifest_version`
- `depends`

### `db summary|top-tables|top-rows|orphan-tables`

These commands return the DB payload shape:

- `database`
- `runtime`
- `rows`
- `row_count`
- `psql`
- `checked`
- `stdout`

Treat `rows` as authoritative.

### `db query --read-only`

Current success shape:

- `database`
- `runtime`
- `row_count`
- `rows`

Current failure shape for blocked SQL:

```json
{
  "error": "read-only query rejected due to mutating SQL token: DELETE"
}
```

Rules:

- `--read-only` is required
- exactly one of `--sql-file` or `--sql-stdin` is required
- raw SQL text is not echoed back by default

### `workflow run`

Workflow execution is foreground text output, not a JSON command. It requires
`--profile`, `--workflow`, `--mode test|test-dev`, and `--allow-write`.

- The named profile owns the target database; a mismatching `--db` is rejected.
- The controller reports the resolved runtime, ensures the Compose `db` service
  is running, then runs Odoo in a disposable named container.
- A runtime/database-scoped lock makes a second invocation for the same
  database fail fast. Workflows with different profile databases may run
  concurrently.
- Recovery removes only stale containers owned by that same runtime/database
  scope. Normal execution uses `--rm` and additionally removes its exact
  container before returning.
- `test-dev` runs the test phase first, then keeps the dev server and database
  lock in the foreground with service ports exposed.

Container isolation does not reset the profile database: module
initialization/upgrade and Odoo tests may mutate it.

### `route list` and `route scan-writes`

Top-level keys:

- `count`
- `routes`
- `parse_errors`

Each route entry currently includes:

- `module`
- `controller`
- `function`
- `paths`
- `methods`
- `auth`
- `route_type`
- `source`
- `line`
- `write_signals`

Interpretation:

- `route list` returns all detected controller routes
- `route scan-writes` returns only routes with heuristic write signals
- `parse_errors` records files static analysis could not parse; these are warnings, not proof no routes exist there

## Text output

Text output mirrors same facts with compact indentation. Do not build downstream parsing around text mode when `--json` is available.

## Missing-data conventions

Normal absences:

- `db_name = False` in `odoo.conf`
- zero matching module rows
- no controller routes in a module or addon root
- empty `parse_errors` or empty `routes`

Reserve hard failures for missing workspace/config, unreadable files, unresolved DB execution paths, or invalid SQL input.

## Safety signals in output

The CLI should make safety posture visible through command names and returned fields:

- `db query` only succeeds in explicit read-only mode
- route scanning is static analysis, not route invocation
- future write-capable commands must expose opt-in state clearly instead of resembling read-only flows
