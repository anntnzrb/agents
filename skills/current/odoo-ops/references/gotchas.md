# Technical Gotchas

Technical facts, environment behaviors, and runtime quirks in Odoo 17.

## Database and SQL

- Translated char fields are stored as `jsonb` in PostgreSQL. Raw SQL queries must extract the locale key (e.g. `name->>'en_US'`) or cast with `::text`. Running `ILIKE` directly on `jsonb` raises a PostgreSQL type error. The `arch_db` column on `ir.ui.view` is also `jsonb`.
- Model name to SQL table name mapping replaces dots with underscores (e.g. `sale.order.line` maps to `sale_order_line`). Special exceptions exist: `ir.actions.server` maps to table `ir_act_server`. Cron triggers use `ir_cron_trigger` and automation triggers use `base_automation_trigger`.
- Inside containerized PostgreSQL, `\copy ... FROM` executes inside the container namespace and cannot access host file paths. Feed data through stdin (e.g. `cat file.csv | db-query ...`).
- `db-restore` skips production `GRANT`, `REVOKE`, and `ALTER DEFAULT PRIVILEGES` statements in SQL dumps for local replicas, preserving COPY data.

## Models, ORM, and Fields

- `ir.actions.server` has no `active` field. Attempting to filter or write `['active', '=', ...]` on server actions raises a missing field error.
- Default `copy()` duplicates field values without modification unless explicitly overridden in `default` or model logic. This can violate PostgreSQL `UNIQUE` constraints (e.g. unique codes or references).
- `@api.onchange` methods execute only in web client form interactions. They never execute during RPC calls, controller executions, or background operations.
- `export_data` is not a pure read; see [Safety model](safety-model.md#read-only-caveats).
- Import batches roll back entirely on any validation or constraint error. In addition, `base_import.import` caches field mappings across calls within the session.
- `@api.constrains` methods run only when a create or write touches a field they declare (`odoo/models.py`, `_validate_fields`). Editing other fields of a record that already violates the rule does not re-check it.
- Writing a field's current value does not update that column: `Field.write` in `odoo/fields.py` drops records whose cached value is unchanged. On models with `_log_access`, `BaseModel.write` still sets `write_date` and `write_uid`, so the first write in a transaction emits an `UPDATE`; a repeat write in the same transaction, or any same-value write on a model without `_log_access`, emits none. Never use a same-value write as a touch to lock a row; lock explicitly with `SELECT ... FOR UPDATE` through `self.env.cr`.
- Writing a `translate=True` field updates only the context language (`lang`, default `en_US`), plus `en_US` when that language is inactive (`odoo/fields.py`, `_String.write`). To rename a record in every language, call `update_field_translations(field_name, {lang: value, ...})`; over RPC it is a `call`, so it produces a plan. A later module upgrade rewrites only the fields the module's data file declares, so it does not restore a name the XML record omits.

## Modules and Data Loading

- A `<function>` tag inside `noupdate="1"` data runs only at install (`odoo/tools/convert.py`, `_tag_function` returns when `noupdate` and mode is not `init`). A module upgrade (`-u`) skips it. For upgrade-time data changes, see the one-time backfill in [Database recipes](db-recipes.md).
- `pre_init_hook` and `post_init_hook` run only on a new install (`odoo/modules/loading.py`, `load_module_graph`, `new_install`), never on upgrade.

## Controllers

- Odoo serves each HTTP request through `retrying` in `odoo/service/model.py`, which retries up to 5 times on the PostgreSQL errors in `PG_CONCURRENCY_ERRORS_TO_RETRY`: `LOCK_NOT_AVAILABLE` (55P03), `SERIALIZATION_FAILURE` (40001), and `DEADLOCK_DETECTED` (40P01). A broad `except Exception` in a controller that swallows these errors disables the retry. Re-raise them before generic handling:

```python
from psycopg2 import OperationalError
from odoo.service.model import PG_CONCURRENCY_ERRORS_TO_RETRY

try:
    ...
except OperationalError as exc:
    if exc.pgcode in PG_CONCURRENCY_ERRORS_TO_RETRY:
        raise
    ...
except Exception:
    ...
```

## Web Client

- List and form views hide the Archive and Unarchive actions when the model's `active` field is `readonly` (`archiveEnabled` in `web/static/src/views/list/list_controller.js` and `web/static/src/views/form/form_controller.js`).

## Scheduled Actions and Server Actions

- `search_read` on `ir.cron` hides inactive cron jobs by default because Odoo ORM applies `active_test=True`. Pass `['active', 'in', [True, False]]` in the domain or include `{'active_test': False}` in context to inspect disabled crons.
- When an `ir.cron` execution fails with an uncaught exception, Odoo rolls back the database transaction. Nothing is written to `ir.logging`, but the scheduler still advances `lastcall` to avoid infinite retry loops.
- Server action `run` and cron `method_direct_trigger` execute immediately with full side effects. Production execution of these methods is denied via RPC.

## Mail, Discuss, and Notifications

- Emails composed through the mail composer are saved in `mail.message` with `message_type='comment'`. Internal notes share the same message type and are distinguished solely by their subtype `mail.mt_note`.
- Context `mail_notrack=True` skips value tracking on create and write, so no tracking messages reach the chatter. `tracking_disable=True` is broader: create and write skip all MailThread features, including auto-subscription, tracking, and posting (`mail/models/mail_thread.py`, class docstring and `write`).
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
