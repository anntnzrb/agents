---
name: odoo-local-ops
description: Safely inspect and operate local Odoo 17 workspaces, databases, modules, and server actions.
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

- Server Actions / ir.actions.server / Execute Python Code
- safe_eval-compatible Python code for Odoo UI actions
- production-safe audit, dry run, execute, or final audit action
- copy a server action to clipboard / write it under /tmp
- mass update from Odoo UI without freezing the browser
## Workflow

1. Discover workspace/runtime from `cwd`.
   - Compose discovery checks `--runtime-dir`, `ODOO17_RUNTIME_DIR`, nearby `odoo17`, then `/Users/Shared/odoo17`.
   - Host discovery walks upward and also inspects immediate child directories.
2. Inspect `odoo.conf` and, when relevant, `.env`.
3. Resolve the active database and DB execution backend.
   - Compose backend uses `docker compose exec -T db psql ...`.
   - Host backend resolves `psql.exe`/`psql` from explicit flag, nearby install tree, `pg_path`, or PATH.
4. Prefer JSON output.
   - For Server Actions, always write the Python snippet to /tmp first, copy with pbcopy, and parse returned JSON from clipboard/output files. Never compose long snippets inline in chat.
   - Default to read-only audit and dry-run snippets. Write snippets require explicit user intent plus precheck/postcheck and rollback-on-failure.
   - Prefer ORM for small writes and business-logic-sensitive operations; use SQL set-based writes only when the UI/ORM path is likely to freeze, spam tracking, or time out, and only with a frozen candidate table and exact postcheck.
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
- `references/server-action-playbook.md` — end-to-end production workflow, /tmp + clipboard, audit/dry-run/execute/final-audit rules
- `references/server-action-safe-eval.md` — Odoo 17 safe_eval context, forbidden imports/opcodes, output semantics
- `references/server-action-sql-safety.md` — when SQL is allowed, temp tables, active_test translation, lock/statement timeouts, rollback rules
- `references/server-action-templates.md` — clipboard-ready template catalog and when to use each template
