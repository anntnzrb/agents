---
name: odoo-local-ops
description: "Inspect and safely operate local Odoo 17 workspaces and databases through the bundled Python CLI. Supports legacy Windows host installs and macOS/Linux Docker Compose runtimes such as /Users/Shared/odoo17. Use whenever the user wants to inspect odoo.conf, discover the active local database, read module metadata, list addon state, inspect PostgreSQL safely, or review likely mutating controller routes. Trigger even when the user only mentions local DB confusion, psql access, Docker Compose Odoo, module tables/models, or route safety."
---

# Odoo Local Ops

Local operational skill for Odoo workspaces.

Supported runtime backends:

- **host**: legacy Windows/local install with host PostgreSQL and `psql.exe`/`psql`.
- **compose**: Docker Compose runtime with `db` and `odoo` services, including the current macOS runtime at `/Users/Shared/odoo17`.

Use the bundled CLI as the public entrypoint:

```bash
uv run /absolute/path/to/odoo-local-ops/scripts/odooctl.py ...
```

Resolve `scripts/odooctl.py` relative to this skill directory, not relative to the Odoo repo. When you invoke it from anywhere inside a local Odoo runtime, custom addons checkout, install root, `server/`, or `server/addons/...`, normal commands should not need `--root`. Use `--root` or `--runtime-dir` only when discovery cannot infer the target.

Do not replace it with raw `psql`, Docker Compose `exec`, shell pipelines, or inline SQL blobs unless the user explicitly asks for lower-level debugging.

## Activation triggers

- Local Odoo workspace inspection on Windows/macOS/Linux
- Docker Compose Odoo runtime inspection
- `odoo.conf`, `.env`
- "which database is this using?"
- addon/module metadata, models, tables, m2m tables, foreign keys
- safe PostgreSQL read queries for Odoo data
- local route listing or controller write-risk review

## Workflow

1. Discover workspace/runtime from `cwd`.
   - Compose discovery checks `--runtime-dir`, `ODOO17_RUNTIME_DIR`, nearby `odoo17`, then `/Users/Shared/odoo17`.
   - Host discovery walks upward and also inspects immediate child directories.
2. Inspect `odoo.conf` and, when relevant, `.env`.
3. Resolve the active database and DB execution backend.
   - Compose backend uses `docker compose exec -T db psql ...`.
   - Host backend resolves `psql.exe`/`psql` from explicit flag, nearby install tree, `pg_path`, or PATH.
4. Prefer JSON output.
5. Keep DB access read-only unless the user explicitly requests a gated write flow.
6. For route review, list routes first, then scan for likely mutating handlers.

## Safe commands

From the current macOS Compose runtime or the custom addons repo:

```bash
uv run /absolute/path/to/odoo-local-ops/scripts/odooctl.py env inspect --json
uv run /absolute/path/to/odoo-local-ops/scripts/odooctl.py db summary --db etech --json
uv run /absolute/path/to/odoo-local-ops/scripts/odooctl.py db top-tables --db etech --limit 20 --json
uv run /absolute/path/to/odoo-local-ops/scripts/odooctl.py addons list --json
uv run /absolute/path/to/odoo-local-ops/scripts/odooctl.py module status crm_espol --db etech --json
uv run /absolute/path/to/odoo-local-ops/scripts/odooctl.py module models crm_espol --db etech --json
uv run /absolute/path/to/odoo-local-ops/scripts/odooctl.py module tables crm_espol --db etech --json
uv run /absolute/path/to/odoo-local-ops/scripts/odooctl.py module m2m crm_espol --db etech --json
uv run /absolute/path/to/odoo-local-ops/scripts/odooctl.py module fks crm_espol --db etech --json
uv run /absolute/path/to/odoo-local-ops/scripts/odooctl.py route list --json
uv run /absolute/path/to/odoo-local-ops/scripts/odooctl.py route scan-writes --json
```

Host-runtime examples still work for Windows installs:

```bash
uv run /absolute/path/to/odoo-local-ops/scripts/odooctl.py env inspect --json
uv run /absolute/path/to/odoo-local-ops/scripts/odooctl.py db query --read-only --sql-file .\tmp\inspect.sql --json
```

## Query guidance

- Prefer `--sql-file` or `--sql-stdin`; do not embed long SQL inside shell strings.
- Default to `--read-only` for ad-hoc queries.
- In local Odoo databases, cast `jsonb` to `::text` before `ILIKE`.
- `ir_model` does not expose `_table`; derive table names with `replace(model,'.','_')` when needed.

## Gated actions

Write-oriented flows are exceptional.

- Only use them after explicit user intent.
- Require an explicit write gate such as `--allow-write` in addition to the write command.
- Summarize the target DB and effect before running a write.
- Do not use write examples as defaults in the skill body.

## Guardrails

- Discover root, config, runtime, database, addons paths, and DB execution dynamically; do not assume fixed install paths.
- Compose runtimes must use the configured `.env`/`.env.example` and never print secrets.
- Output JSON-first with brief text fallback.
- Never print secrets.
- Route scans are heuristic risk indicators, not proof of a write.

## Reference docs

Read these when the task needs deeper rules:

- `references/runtime-discovery.md` — workspace, Compose, config, DB, and psql resolution.
- `references/safety-model.md` — read-only defaults, redaction, write gates, and route risk rules.
- `references/db-recipes.md` — DB inspection command selection and SQL recipes.
- `references/output-contracts.md` — JSON output shapes and failure contracts.
- `references/route-safety.md` — controller route risk heuristics.
