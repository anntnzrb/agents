---
name: odoo-local-ops
description: Safely inspect and operate local Odoo 17 workspaces, databases, modules, and server actions.
---

# Odoo Local Ops

Local operational skill for Odoo workspaces.

Supported runtime backends:

- **host**: legacy Windows/local install with host PostgreSQL and `psql.exe`/`psql`.
- **compose**: Docker Compose runtime with `db` and `odoo` services.

Use the bundled CLI as the public entrypoint:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Resolve `<skill-dir>` independently from the Odoo repo. Normal commands should not need `--root` when invoked inside a discoverable runtime or workspace. Use `--root` or `--runtime-dir` only when discovery cannot infer the target.

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
- copy a server action to clipboard / stage it under `<temp-dir>`
- mass update from Odoo UI without freezing the browser
## Workflow

1. Discover workspace/runtime from `cwd`.
   - Compose discovery checks `--runtime-dir`, `ODOO17_RUNTIME_DIR`, then nearby `odoo17` runtimes.
   - Host discovery walks upward and also inspects immediate child directories.
2. Inspect `odoo.conf` and, when relevant, `.env`.
3. Resolve the active database and DB execution backend.
   - Compose backend uses `docker compose exec -T db psql ...`.
   - Host backend resolves `psql.exe`/`psql` from explicit flag, nearby install tree, `pg_path`, or PATH.
4. Prefer JSON output.
   - For Server Actions, always stage the Python snippet under `<temp-dir>` first, then copy it and parse returned JSON from clipboard/output files. Never compose long snippets inline in chat.
   - Default to read-only audit and dry-run snippets. Write snippets require explicit user intent plus precheck/postcheck and rollback-on-failure.
   - Prefer ORM for small writes and business-logic-sensitive operations; use SQL set-based writes only when the UI/ORM path is likely to freeze, spam tracking, or time out, and only with a frozen candidate table and exact postcheck.
5. Keep DB access read-only unless the user explicitly requests a gated write flow.
6. For route review, list routes first, then scan for likely mutating handlers.

## Safe commands

From a discoverable Compose runtime or the custom addons repo:

```bash
uv run --script <skill-dir>/scripts/cli.py env inspect --json
uv run --script <skill-dir>/scripts/cli.py db summary --db <database> --json
uv run --script <skill-dir>/scripts/cli.py db top-tables --db <database> --limit 20 --json
uv run --script <skill-dir>/scripts/cli.py addons list --json
uv run --script <skill-dir>/scripts/cli.py module status crm_espol --db <database> --json
uv run --script <skill-dir>/scripts/cli.py module models crm_espol --db <database> --json
uv run --script <skill-dir>/scripts/cli.py module tables crm_espol --db <database> --json
uv run --script <skill-dir>/scripts/cli.py module m2m crm_espol --db <database> --json
uv run --script <skill-dir>/scripts/cli.py module fks crm_espol --db <database> --json
uv run --script <skill-dir>/scripts/cli.py route list --json
uv run --script <skill-dir>/scripts/cli.py route scan-writes --json
```

Host-runtime examples still work for Windows installs:

```bash
uv run --script <skill-dir>/scripts/cli.py env inspect --json
uv run --script <skill-dir>/scripts/cli.py db query --read-only --sql-file <sql-file> --json
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

### Profiled local workflows

The `workflow run` controller owns a profile's database, modules, test tags,
Compose lifecycle, and foreground test/dev execution. It is write-gated because
module initialization and upgrade mutate the selected database.
Workflow runs use disposable, uniquely named containers with a deterministic
runtime/database-scoped prefix. Profiles with different databases can run
concurrently; the same database is fail-fast serialized for the complete
test/test-dev lifecycle.

Container isolation is not database-state isolation: profiles still own and
mutate their databases. Recovery removes only `odooctl` containers scoped to the
same runtime and database, never unrelated Odoo containers; `--rm` leaves no
per-run Docker artifact.

Etech profiles must run from the custom addons checkout, with an explicit
`--allow-write` gate after the operator confirms the profile-owned database and
the intended module initialization or upgrade.

```bash
uv run --script <skill-dir>/scripts/cli.py workflow run --profile etech --workflow crm --mode test --allow-write
```

Use `--mode test-dev` only after confirming that its foreground server should
hold that database lock and expose service ports.

## Guardrails

- Discover root, config, runtime, database, addons paths, and DB execution dynamically; do not assume fixed install paths.
- Compose runtimes must use the configured `.env`/`.env.example` and never print secrets.
- Output JSON-first with brief text fallback.
- Never print secrets.
- Route scans are heuristic risk indicators, not proof of a write.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Workspace, Compose, config, DB, psql resolution | `references/runtime-discovery.md` | Discovery is ambiguous or fails |
| Read-only defaults, redaction, write gates | `references/safety-model.md` | Before DB or route operations |
| DB commands and SQL recipes | `references/db-recipes.md` | Selecting DB inspection commands |
| JSON shapes and failure contracts | `references/output-contracts.md` | Consuming CLI output programmatically |
| Controller route heuristics | `references/route-safety.md` | Reviewing route write risk |
| Production Server Action workflow | `references/server-action-playbook.md` | Auditing, dry-running, writing, or closing out |
| Odoo 17 capability map | `references/server-action-capabilities.md` | Choosing actions, automation, webhooks, cron, or modules |
| `safe_eval` constraints | `references/server-action-safe-eval.md` | Authoring Execute Python Code snippets |
| Set-based SQL safeguards | `references/server-action-sql-safety.md` | SQL writes are explicitly authorized |
| Clipboard-ready templates | `references/server-action-templates.md` | Selecting a Server Action template |
