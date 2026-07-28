# DB Recipes

All examples use the bundled CLI and assume read-only intent.

Use `uv run --script <skill-dir>/scripts/cli.py ...` as the public front door. Do not fall back to raw `psql`, Docker Compose `exec`, or ad-hoc shell quoting unless debugging the skill itself.

## Runtime backends

The same commands work against:

- host runtimes, where the CLI resolves `psql.exe`/`psql`
- Compose runtimes, where the CLI runs `psql` inside the `db` service

Use `--db <database>` whenever the active DB is ambiguous or the operation must
target a specific database. Do not infer a workflow profile's database from the
runtime default.

## Command selection

### `db summary`

Fast health snapshot of the active local database:

- resolved database name
- object counts by kind
- connection target metadata
- runtime backend metadata

```text
uv run --script <skill-dir>/scripts/cli.py db summary --db <database> --json
```

Prefer this first when you need to confirm the effective local DB.

### `db top-tables --limit N`

Use for table size pressure, storage hotspots, or large relation suspects.

```text
uv run --script <skill-dir>/scripts/cli.py db top-tables --db <database> --limit 25 --json
```

### `db top-rows --limit N`

Use when row volume matters more than bytes.

```text
uv run --script <skill-dir>/scripts/cli.py db top-rows --db <database> --limit 25 --json
```

### `db orphan-tables --limit N`

Find physical tables that do not map cleanly to active `ir_model` rows.

```text
uv run --script <skill-dir>/scripts/cli.py db orphan-tables --db <database> --limit 50 --json
```

Treat the result as an investigation queue, not as a deletion list.

### `db query --read-only`

Use for ad-hoc inspection too specific for a canned probe.

```text
uv run --script <skill-dir>/scripts/cli.py db query --db <database> --read-only --sql-file <sql-file> --json
```

or:

```text
uv run --script <skill-dir>/scripts/cli.py db query --db <database> --read-only --sql-stdin --json
```

Rules:

- `--read-only` is the normal mode.
- Pass SQL via `--sql-file` or `--sql-stdin`, not inline shell blobs.
- The backend applies read-only safeguards.
- Obviously mutating SQL is rejected before execution.

If DB execution cannot be resolved, the command should fail clearly and report which backend/path was attempted.

## Module-aware inspection

Use module-scoped commands before ad-hoc SQL when possible.

```text
uv run --script <skill-dir>/scripts/cli.py module status <module> --db <database> --json
uv run --script <skill-dir>/scripts/cli.py module models <module> --db <database> --json
uv run --script <skill-dir>/scripts/cli.py module tables <module> --db <database> --json
uv run --script <skill-dir>/scripts/cli.py module m2m <module> --db <database> --json
uv run --script <skill-dir>/scripts/cli.py module fks <module> --db <database> --json
```

## Two local truth rules

### 1. Cast `jsonb` to text before `ILIKE`

PostgreSQL will not apply `ILIKE` directly to `jsonb`.

Good:

```sql
SELECT id
FROM some_table
WHERE json_payload::text ILIKE '%needle%';
```

Bad:

```sql
SELECT id
FROM some_table
WHERE json_payload ILIKE '%needle%';
```

### 2. `ir_model` does not expose `_table`

Odoo model metadata does not store the Python `_table` attribute in `ir_model`. For the common case, derive the default table name with:

```sql
replace(model, '.', '_')
```

Examples:

- `crm.lead` -> `crm_lead`
- `budget.request` -> `budget_request`
- `res.partner` -> `res_partner`

This is good enough for module table inventories, orphan-table comparisons, and FK summaries. It is not a promise that every custom model uses the default table name.

## Failure modes to expect

### `db_name = False`

Valid. Continue discovery and surface that configured DB name is unset. Prefer explicit `--db` or known local Compose metadata.

### Missing DB execution backend

Host runtime: report checked `--psql`, nearby install-tree candidates, `pg_path`, and PATH.

Compose runtime: report Docker Compose availability and `db` service execution failure.

## Practical flow

For most investigations:

1. `env inspect --json`
2. `db summary --db <database> --json`
3. `module status <module> --db <database> --json`
4. `module tables <module> --db <database> --json` or `db top-tables --db <database> --limit 25 --json`
5. `db query --db <database> --read-only ... --json` only when canned probes are not enough

Keep examples and normal usage read-only. Any future write-capable DB verb must require explicit user approval plus `--allow-write` and should never be the default path.
