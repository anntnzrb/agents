---
disable-model-invocation: true
name: odoo-ops
description: "Odoo 17 dev server, test runner, lint/format, read-only JSON-RPC queries, workspace and database inspection."
license: AGPL-3.0-or-later
---

# Odoo Ops

Single-control skill for Odoo 17 dev stack, test runner, linter/formatter, and PostgreSQL inspection.

Use the bundled CLI as the single entrypoint:

```bash
uv run --script <skill-dir>/scripts/cli.py ...
```

## The 5 Core Commands

### 1. Dev Runner (`dev`)
Starts the local development stack directly in foreground with instant hot-reloading (`--dev=all`). (Press `Ctrl-C` to stop).

```bash
uv run --script <skill-dir>/scripts/cli.py dev <workflow> [--pretty]
```

### 2. Test Runner (`test`)
Executes unit tests in an isolated headless container with real-time log streaming, graceful cancellation, and automatic container cleanup.

```bash
uv run --script <skill-dir>/scripts/cli.py test <workflow|module> [--json]
uv run --script <skill-dir>/scripts/cli.py test <module> --tags :TestClass.test_method  # Fast targeted test
uv run --script <skill-dir>/scripts/cli.py test <workflow> --parallel [-j 4]          # Concurrency across modules
```
- **Granular Tag Filtering**: Pass `--tags` / `--test-tags` to run specific test classes or methods in seconds without full suite overhead.
- **Parallel Module Runner**: Pass `--parallel` / `-j` to execute independent module suites concurrently in isolated containers.
- **Network & Port Isolation**: Test containers run with `--no-http` to prevent port 8069 socket collisions.
- **Database Resolution**: Single-module tests automatically inherit the correct profile workflow database (e.g. `erptech_0817-crm`).
- Accurate pass/fail evaluation based on Odoo test result summaries, avoiding false positives on expected log errors.
### 3. Linter Gate (`lint`)
Runs Ruff linter across workflow modules or single module with `<skill>/config/ruff.toml`.

```bash
uv run --script <skill-dir>/scripts/cli.py lint <workflow|module> [--fix] [--pretty]
```

### 4. Formatter Gate (`fmt`)
Runs Ruff formatter across workflow modules or single module.

```bash
uv run --script <skill-dir>/scripts/cli.py fmt <workflow|module> [--check] [--pretty]
```


### 5. XML View & AST Linter (`lint-views`)
Runs the AST and semantic validator for Odoo 17 XML views and QWeb templates (checks deprecated `attrs`/`states`, `column_invisible` in list/tree views, brittle `@class` and positional XPaths, duplicate fields, accessible alert roles, and extensible group/page naming).

```bash
uv run --script <skill-dir>/scripts/cli.py lint-views <workflow|module> [--strict] [--json]
uv run --script <skill-dir>/scripts/cli.py lint-views --all [--strict]
```
## Stack Control & Logs

```bash
uv run --script <skill-dir>/scripts/cli.py stop     # Stop development stack and free resources
uv run --script <skill-dir>/scripts/cli.py logs     # Follow live server logs
```

## Workflows & Profiles

Workflows are defined in `<skill>/profiles/<profile>.json`:

- **`crm`**: `erptech_0817-crm` (CRM, WhatsApp, B2B, Budget, Templates)


## Production & Remote JSON-RPC (`rpc`)

Execute queries and guarded mutations against remote or local Odoo instances via JSON-RPC.
Methods are validated against strict allowlists:
- **Safe Introspection (Read-Only)**: Always permitted without flags (`search`, `search_read`, `read`, `search_count`, `read_group`, `fields_get`, `get_view`, `get_views`, `name_search`, `name_get`, `export_data`, `get_metadata`, `get_external_id`, `default_get`, `check_access_rights`, `user_has_groups`, `onchange`).
- **State Mutations**: Strictly guarded; requires explicit `--write` flag (`create`, `write`, `unlink`, `copy`, `action_archive`, `action_unarchive`, `toggle_active`). Calling any mutation without `--write` aborts immediately with `PermissionError`.

### Configuration
Credentials and connection parameters are loaded from `<skill-dir>/.env` (see `.env.example` in the skill root for full schema) or environment variables:
- `ODOO_RPC_URL`: JSON-RPC URL endpoint (e.g. `https://erp.example.com/jsonrpc`)
- `ODOO_RPC_DB`: Database name
- `ODOO_RPC_USER`: User email/login
- `ODOO_RPC_TOKEN`: API token / password (or path via `ODOO_RPC_TOKEN_PATH` / `~/.erp-token`)
- `ODOO_RPC_VERIFY_SSL`: Boolean (`true` by default; set to `false` or pass `--insecure` for self-signed certificates)

### Safe Introspection & Query Commands

```bash
# 1. Search and read records
uv run --script <skill-dir>/scripts/cli.py rpc search_read <model> '[["active", "=", true]]' --fields id name --limit 10

# 2. Count records matching a domain
uv run --script <skill-dir>/scripts/cli.py rpc count <model> '[["stage_id", "=", 1]]'

# 3. Read specific records by ID
uv run --script <skill-dir>/scripts/cli.py rpc read <model> '[101, 102]' --fields name display_name

# 4. Inspect model fields definition
uv run --script <skill-dir>/scripts/cli.py rpc fields_get <model> --fields name stage_id

# 5. Inspect view architecture
uv run --script <skill-dir>/scripts/cli.py rpc get_view <model> --view-type form

# 6. Inspect metadata (create_date, write_date, XML IDs)
uv run --script <skill-dir>/scripts/cli.py rpc metadata <model> '[101, 102]'

# 7. Retrieve External XML IDs
uv run --script <skill-dir>/scripts/cli.py rpc external_id <model> '[101, 102]'

# 8. Retrieve default field values
uv run --script <skill-dir>/scripts/cli.py rpc default_get <model> field1 field2

# 9. Check access rights
uv run --script <skill-dir>/scripts/cli.py rpc check_access <model> --operation read
```

### State Mutation Commands (Require `--write`)

```bash
# 1. Create a record
uv run --script <skill-dir>/scripts/cli.py rpc --write create <model> '{"name": "New Record"}'

# 2. Update existing records
uv run --script <skill-dir>/scripts/cli.py rpc --write write <model> '[101]' '{"name": "Updated Name"}'

# 3. Duplicate a record
uv run --script <skill-dir>/scripts/cli.py rpc --write copy <model> 101 --default '{"name": "Copy of Record"}'

# 4. Archive records (active=False)
uv run --script <skill-dir>/scripts/cli.py rpc --write archive <model> '[101, 102]'

# 5. Unarchive records (active=True)
uv run --script <skill-dir>/scripts/cli.py rpc --write unarchive <model> '[101, 102]'

# 6. Delete records permanently
uv run --script <skill-dir>/scripts/cli.py rpc --write unlink <model> '[101]'
```

### Production Batch Normalization & Migration Protocols

When developing or executing mass data sanitation scripts in production:
1. **Mandatory Dry-Run First**: Always implement and execute a `--dry-run` pass before writing. Output total qualifying records, filtered-out edge cases (e.g. records locked by stage/business constraints), and before/after samples.
2. **Chunked RPC Batching (250–500 records)**: Never mutate thousands of records in a single RPC transaction. Process in discrete chunks with explicit progress logging to prevent table locks and HTTP connection timeouts.
3. **Preflight Model Constraint Audit**: Check active `@api.constrains` on the target model prior to execution. If certain stages or states disallow changes, isolate or exclude those IDs cleanly.
4. **Decoupled Dedicated Logging**: Stream batch execution progress to a dedicated log file (e.g. `/tmp/odoo_migration.log`) and monitor via background tail (`tail -f /tmp/odoo_migration.log`) to preserve conversation context.
Linter and formatter configurations are centralized in `<skill>/config/ruff.toml`.
