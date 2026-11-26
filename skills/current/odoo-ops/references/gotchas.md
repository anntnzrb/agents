# Technical Gotchas

Technical facts, environment behaviors, and runtime quirks of Odoo, verified on 17. Version-specific APIs live in `odoo<version>.md`; on another version, check each fact against the provisioned source before relying on it. Source paths below cite the Odoo 17 layout (`odoo/models.py`, `odoo/fields.py`, `odoo/api.py`); on 19 the ORM moved to `odoo/orm/`, see the path map in [odoo19.md](odoo19.md#source-path-map).

## Database and SQL

- Translated char fields are stored as `jsonb` in PostgreSQL. Raw SQL queries must extract the locale key (e.g. `name->>'en_US'`) or cast with `::text`. Running `ILIKE` directly on `jsonb` raises a PostgreSQL type error. The `arch_db` column on `ir.ui.view` is also `jsonb`.
- Model name to SQL table name mapping replaces dots with underscores (e.g. `sale.order.line` maps to `sale_order_line`). Special exceptions exist: `ir.actions.server` maps to table `ir_act_server`. Cron triggers use `ir_cron_trigger`; automation rules use `base_automation` (there is no trigger table).
- Inside containerized PostgreSQL, `\copy ... FROM` executes inside the container namespace and cannot access host file paths. With `db-query --file -`, stdin supplies the SQL itself. It cannot also supply CSV data.
- `db-restore` skips production `GRANT`, `REVOKE`, and `ALTER DEFAULT PRIVILEGES` statements in SQL dumps for local replicas, preserving COPY data.

## Models, ORM, and Fields

- `ir.actions.server` has no `active` field. Attempting to filter or write `['active', '=', ...]` on server actions raises a missing field error.
- Default `copy()` duplicates field values without modification unless explicitly overridden in `default` or model logic. This can violate PostgreSQL `UNIQUE` constraints (e.g. unique codes or references).
- `@api.onchange` methods execute only in web client form interactions. They never execute during RPC calls, controller executions, or background operations.
- `export_data` is not a pure read; see [Safety model](safety-model.md#read-only-caveats).
- Import batches roll back entirely on any validation or constraint error.
- `@api.constrains` methods run only when a create or write touches a field they declare (`odoo/models.py`, `_validate_fields`). Editing other fields of a record that already violates the rule does not re-check it.
- Writing a field's current value does not update that column: `Field.write` in `odoo/fields.py` drops records whose cached value is unchanged. On models with `_log_access`, `BaseModel.write` still sets `write_date` and `write_uid`, so the first write in a transaction emits an `UPDATE`; a repeat write in the same transaction, or any same-value write on a model without `_log_access`, emits none. Never use a same-value write as a touch to lock a row; lock explicitly with `SELECT ... FOR UPDATE` through `self.env.cr`.
- `with self.env.cr.savepoint():` rolls back only when an exception leaves the block (`odoo/sql_db.py`, `Savepoint.__exit__`). Catching a database error inside the block makes the exit run `RELEASE SAVEPOINT` on an aborted transaction, which raises `InFailedSqlTransaction`. Put the `try` outside the `with`:

```python
import psycopg2

try:
    with self.env.cr.savepoint():
        record = self.create(vals)
except psycopg2.errors.UniqueViolation:
    record = self.search([("code", "=", vals["code"])], limit=1)
```

- Search-then-create races under concurrent requests. Back uniqueness with a database unique constraint (declared as `odoo<version>.md` describes), then handle the violation as above.
- Never call `self.env.cr.commit()` in model or controller code: the request owns the transaction, and a partial commit survives its later rollback. In a cron, commit only as a deliberate checkpoint after a complete, self-consistent batch.
- `Command.unlink(id)` on a One2many deletes the child record when the inverse many2one has `ondelete='cascade'`; otherwise it sets the inverse to `False` (`odoo/fields.py`, `Command.unlink`). `Command.delete(id)` always deletes.
- Writing a `translate=True` field updates only the context language (`lang`, default `en_US`), plus `en_US` when that language is inactive (`odoo/fields.py`, `_String.write`). To rename a record in every language, call `update_field_translations(field_name, {lang: value, ...})`; over RPC it is a `call`, so it produces a plan. A later module upgrade rewrites only the fields the module's data file declares, so it does not restore a name the XML record omits.

## Modules and Data Loading

- A `<function>` tag inside `noupdate="1"` data runs only at install (`odoo/tools/convert.py`, `_tag_function` returns when `noupdate` and mode is not `init`). A module upgrade (`-u`) skips it. For upgrade-time data changes, see the one-time backfill in [Database recipes](db-recipes.md).
- `-i` on an installed module loads it in install mode (`odoo/modules/loading.py`, `load_module_graph`; on 17 also `odoo/modules/graph.py`, `add_modules`): data files rewrite `noupdate` records and rerun `noupdate` `<function>` tags. A local run with `-i <module>` therefore hides upgrade-only failures and can trigger large stored recomputes that a deploy never runs. Upgrade installed modules with `-u` alone.
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
- OWL template expressions resolve bare names on the component context. JavaScript globals such as `Boolean(value)` can fail as `ctx.Boolean is not a function`; use `!!value` instead.
- `t-att-disabled="value"` renders `disabled="null"` when `value` is `null`, leaving the control disabled. Coerce the expression to a boolean, for example `t-att-disabled="!!value"`.

## Scheduled Actions and Server Actions

- `search_read` on `ir.cron` hides inactive cron jobs by default because Odoo ORM applies `active_test=True`. For RPC `search_read`, include `["active", "in", [true, false]]` in the domain. For `rpc call ir.cron search_read`, you can pass `--kwargs '{"context":{"active_test":false}}'`.
- When an `ir.cron` execution fails with an uncaught exception, Odoo rolls back the database transaction. Nothing is written to `ir.logging`, but the scheduler still advances `lastcall` to avoid infinite retry loops.
- Server action `run` and cron `method_direct_trigger` execute immediately with full side effects. Production execution of these methods is denied via RPC.

## Mail, Discuss, and Notifications

- Emails composed through the mail composer are saved in `mail.message` with `message_type='comment'`. Internal notes share the same message type and are distinguished solely by their subtype `mail.mt_note`.
- Context `mail_notrack=True` skips value tracking on create and write, so no tracking messages reach the chatter. `tracking_disable=True` is broader: create and write skip all MailThread features, including auto-subscription, tracking, and posting (`mail/models/mail_thread.py`, class docstring and `write`).
- Calling `discuss.channel.add_members()` pins the channel for the added members and posts a joined message by default (`post_joined_message=True`). On 17 it opens chat windows only with `open_chat_window=True`; 19 has no such argument.

## Container, System, and Environment

- Always connect to `127.0.0.1` rather than `localhost`. On systems where `localhost` resolves to IPv6 (`::1`), Odoo and PostgreSQL listeners bound to IPv4 reject the connection.
- NixOS Python environments using `urllib` require `SSL_CERT_FILE` set in the environment to locate the system certificate authority bundle.
- Debugging a hung test container: `SIGQUIT` (signal 3) prints a Python thread dump to the container log for stack inspection. `SIGUSR1` prints memory statistics.

## Testing and QUnit

- Test files omitted from `tests/__init__.py` are never discovered or executed by Odoo test runners.
- Test classes default to tags `standard` and `at_install` (`odoo/tests/common.py`, `MetaCase`). `HttpCase` and tour tests need `@tagged("post_install", "-at_install")` so every module is loaded first.
- `odoo.tests.common.Form` is deprecated since 17.0; import `Form` from `odoo.tests`.
- A database neutralization banner in the test environment alters DOM layout and can break positional selectors in the first executed test.
- `sessionStorage` state is not cleared between individual QUnit tests, which can reorder test expectations or leak mock state.
- Any unhandled `console.error` emitted during a test immediately fails that test case in the test runner.
