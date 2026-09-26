# Technical Gotchas

Technical facts, environment behaviors, and runtime quirks in Odoo 17.

## Database and SQL

- Translated char fields are stored as `jsonb` in PostgreSQL. Raw SQL queries must extract the locale key (e.g. `name->>'en_US'`) or cast with `::text`. Running `ILIKE` directly on `jsonb` raises a PostgreSQL type error. The `arch_db` column on `ir.ui.view` is also `jsonb`.
- Model name to SQL table name mapping replaces dots with underscores (e.g. `crm.espol.periodo` maps to `crm_espol_periodo`). Special exceptions exist: `ir.actions.server` maps to table `ir_act_server`. Cron triggers use `ir_cron_trigger` and automation triggers use `base_automation_trigger`.
- Inside containerized PostgreSQL, `\copy ... FROM` executes inside the container namespace and cannot access host file paths. Feed data through stdin (e.g. `cat file.csv | db-query ...`).
- Restoring a replica from a database dump without its accompanying filestore causes missing binary attachments and broken spreadsheet dashboards. This is an expected artifact of SQL-only dumps, not a code defect.

## Models, ORM, and Fields

- `ir.actions.server` has no `active` field. Attempting to filter or write `['active', '=', ...]` on server actions raises a missing field error.
- Default `copy()` duplicates field values without modification unless explicitly overridden in `default` or model logic. This can violate PostgreSQL `UNIQUE` constraints (e.g. unique codes or references).
- `@api.onchange` methods execute only in web client form interactions. They never execute during RPC calls, controller executions, or background operations.
- `export_data` is not a pure read. [`odoo/models.py`](https://github.com/odoo/odoo/blob/17.0/odoo/models.py) routes `export_data` through `_export_rows` and `__ensure_xml_id`, which inserts new rows into `ir_model_data` when records lack XML IDs. Use `read` or `search_read` for pure inspection.
- Import batches roll back entirely on any validation or constraint error. In addition, `base_import.import` caches field mappings across calls within the session.

## Scheduled Actions and Server Actions

- `search_read` on `ir.cron` hides inactive cron jobs by default because Odoo ORM applies `active_test=True`. Pass `['active', 'in', [True, False]]` in the domain or include `{'active_test': False}` in context to inspect disabled crons.
- When an `ir.cron` execution fails with an uncaught exception, Odoo rolls back the database transaction. Nothing is written to `ir.logging`, but the scheduler still advances `lastcall` to avoid infinite retry loops.
- Server action `run` and cron `method_direct_trigger` execute immediately with full side effects. Production execution of these methods is denied via RPC.

## Mail, Discuss, and Notifications

- Emails composed through the mail composer are saved in `mail.message` with `message_type='comment'`. Internal notes share the same message type and are distinguished solely by their subtype `mail.mt_note`.
- Calling `discuss.channel.add_members()` automatically pins the channel (`is_pinned=True`) and opens chat windows for added members, creating reactive state in their frontend sessions.

## Container, System, and Environment

- Always connect to `127.0.0.1` rather than `localhost`. On systems where `localhost` resolves to IPv6 (`::1`), Odoo and PostgreSQL listeners bound to IPv4 reject the connection.
- Quoted paths containing a tilde (such as `"--token-path ~/..."`) prevent shell tilde expansion, causing path resolution failures.
- NixOS Python environments using `urllib` require `SSL_CERT_FILE` set in the environment to locate the system certificate authority bundle.
- The Odoo 17 runtime container runs Python 3.10. `datetime.UTC` (introduced in Python 3.11) is unavailable; use `timezone.utc` from `datetime` instead.
- Debugging a hung test container: `SIGQUIT` (signal 3) prints a Python thread dump to the container log for stack inspection. `SIGUSR1` prints memory statistics.

## Testing and QUnit

- Test files omitted from `tests/__init__.py` are never discovered or executed by Odoo test runners.
- Odoo 17 bundles QUnit 2.9.1. Modern assertion helpers like `assert.true()` and `assert.false()` do not exist; use `assert.ok()` or strict equality checks.
- A database neutralization banner in the test environment alters DOM layout and can break positional selectors in the first executed test.
- `sessionStorage` state is not cleared between individual QUnit tests, which can reorder test expectations or leak mock state.
- Any unhandled `console.error` emitted during a test immediately fails that test case in the test runner.
