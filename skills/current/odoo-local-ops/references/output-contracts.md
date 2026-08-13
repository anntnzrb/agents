# Output Contracts

CLI JSON-first; text fallback. MUST use `--json` for tool/agent consumers; text only for quick human inspection. Outputs command-shaped, not generic envelopes.

## Core

- Success: command-specific data only.
- Expected absence: explicit `null`, empty lists, or empty counts.
- Errors: actionable, secret-free.
- NEVER emit raw secret values from `odoo.conf`, `.env`, or environment.

## Errors

```json
{
  "error": "psql executable not found; use --psql, run from the Odoo install tree, or configure pg_path",
  "checked": [
    "C:\\path\\nearby\\PostgreSQL\\bin\\psql.exe",
    "PATH lookup via psql"
  ]
}
```

`error` always primary message; `checked` appears when executable/path/runtime discovery matters; failure exits non-zero. Read-only SQL rejection also uses `error`.

## Success contracts

### `env inspect`

Top-level keys: `runtime`, `root`, `config_path`, `config`, `addons_paths`, `effective_db_name`, `psql`.

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

Host-runtime: same shape, but `runtime.backend: windows-host`; `psql.path` is host executable. `config` and runtime env automatically redact secret-like keys.

### `addons list`

Top-level: `count`, `modules`. Each entry: `module`, `path`, `addons_dir`.

### `addons manifest <module>`

Top-level: `module`, `path`, `manifest`. `manifest` is literal data parsed from `__manifest__.py`; treat as filesystem metadata, not install-state proof.

### `module status|models|tables|m2m|fks`

DB-backed commands return the PostgreSQL helper payload directly, or a small module wrapper plus DB rows. Common payload: `database`, `runtime`, `rows`, `row_count`, `psql`, `checked`, `stdout`.

- `rows`: canonical parsed result.
- `row_count`: parsed CSV row count.
- `psql`: host executable or Compose service path.
- `checked`: discovery attempts.
- `stdout`: raw CSV traceability, not main contract.

`module status` additionally: `module`, `path`, `manifest_version`, `depends`.

### `db summary|top-tables|top-rows|orphan-tables`

Payload: `database`, `runtime`, `rows`, `row_count`, `psql`, `checked`, `stdout`. `rows` authoritative.

### `db clone`

Dry-run by default. Success payload: `operation: db.clone`, `status: dry-run|cloned`, `source_database`, `target_database`, `admin_database`, `destructive`, `target_exists`, `replace_requested`, `preflight`.

Successful writes additionally include `replaced`, `postflight`, `checked`. `preflight` and `postflight` report existence and active connection counts for both source and target. NEVER return success without a postflight target-exists check.

### `db query --read-only`

Success: `database`, `runtime`, `row_count`, `rows`.

```json
{
  "error": "read-only query rejected due to mutating SQL token: DELETE"
}
```

Rules: `--read-only` required; exactly one of `--sql-file` or `--sql-stdin` required; raw SQL not echoed by default.

### `workflow run`

Foreground text, not JSON. Requires `--profile`, `--workflow`, `--mode test|test-dev`, `--allow-write`.

- Named profile owns target database; mismatching `--db` rejected.
- Controller reports resolved runtime, ensures Compose `db` service is running, then runs Odoo in a disposable named container.
- Runtime/database-scoped lock: second invocation for same database fails fast; different profile databases may run concurrently.
- Recovery removes only stale containers owned by that runtime/database scope. Normal execution uses `--rm` and additionally removes its exact container before return.
- `test-dev`: test phase first; then dev server and database lock remain foregrounded with service ports exposed.
- Container isolation does not reset profile database; module initialization/upgrade and Odoo tests may mutate it.

### `route list` / `route scan-writes`

Top-level: `count`, `routes`, `parse_errors`. Each route: `module`, `controller`, `function`, `paths`, `methods`, `auth`, `route_type`, `source`, `line`, `write_signals`.

- `route list`: all detected controller routes.
- `route scan-writes`: only routes with heuristic write signals.
- `parse_errors`: files static analysis could not parse; warnings, not proof that no routes exist there.

## Text output

Mirrors the same facts with compact indentation. Do not build downstream parsing on text when `--json` is available.

## Missing data

Normal absences: `db_name = False` in `odoo.conf`; zero matching module rows; no controller routes in a module/addon root; empty `parse_errors` or `routes`.

Hard failures reserved for missing workspace/config, unreadable files, unresolved DB execution paths, or invalid SQL input.

## Safety

- `db query` succeeds only in explicit read-only mode.
- Route scanning is static analysis, not route invocation.
- Future write-capable commands MUST expose opt-in state clearly, not resemble read-only flows.
