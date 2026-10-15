# Database Recipes

Use these commands exclusively for local replica databases. Read [Runtime discovery](runtime-discovery.md) and [Safety model](safety-model.md) first.

Naming convention: `<prodDB>_seed_<YYYYMMDD>` for the untouched baseline (restored once from a DBA dump) and `<prodDB>_work_<YYYYMMDD>` for the disposable working replica. Use lowercase letters and underscores only; never use hyphens, which require identifier quoting in PostgreSQL.

The CLI resolves the default database from the active profile (`effective_database`). Pass `--db <database_name>` to target a specific replica.

## Database Inventory and Inspection

```text
# List local PostgreSQL databases
uv run --script <skill-dir>/scripts/cli.py db-list

# Inspect database vitals, size, and module count
uv run --script <skill-dir>/scripts/cli.py db-summary --db <prodDB>_work_<YYYYMMDD> --json

# List largest database tables by disk usage
uv run --script <skill-dir>/scripts/cli.py db-tables --db <prodDB>_work_<YYYYMMDD> --limit 20 --json
```

## SQL Queries

Execute queries through `db-query`. Default executions run in a read-only transaction; use `--unsafe` for intentional local mutations.

```text
# Inline query (defaults to profile database)
uv run --script <skill-dir>/scripts/cli.py db-query 'SELECT current_database()'

# Targeted query on a specific replica
uv run --script <skill-dir>/scripts/cli.py db-query 'SELECT count(*) FROM res_partner' --db <prodDB>_work_<YYYYMMDD>

# Long SQL query via file (write to <temp-dir> first)
uv run --script <skill-dir>/scripts/cli.py db-query --file <temp-dir>/audit.sql --db <prodDB>_work_<YYYYMMDD> --json
```

For large queries or data fixes, write the SQL into `<temp-dir>/query.sql` and pass `--file`. You do not need to delete temporary files.

## ORM Shell Execution

The `shell` command executes Python code using the full Odoo ORM environment on a local replica. It requires the `dev` server to be running:

```text
# Run ORM script from file (commits changes on clean exit by default)
uv run --script <skill-dir>/scripts/cli.py shell --file <temp-dir>/script.py --db <prodDB>_work_<YYYYMMDD>

# Run ORM script with rollback to test without altering data
uv run --script <skill-dir>/scripts/cli.py shell --file <temp-dir>/script.py --db <prodDB>_work_<YYYYMMDD> --rollback
```

The `shell` command runs against local replicas only; it strictly refuses execution against seed databases (`_seed_`) and production endpoints.

## Container Health, Logs, and Lifecycle

Manage local container infrastructure through dedicated CLI subcommands rather than raw container tools or curl:

```text
# Verify HTTP service availability on 127.0.0.1 (replaces curl)
uv run --script <skill-dir>/scripts/cli.py health --wait 30

# Tail container logs by target container
uv run --script <skill-dir>/scripts/cli.py logs -c web -f
uv run --script <skill-dir>/scripts/cli.py logs -c db -n 100
uv run --script <skill-dir>/scripts/cli.py logs -c test

# End a session (keeps data) or stop only the web container
uv run --script <skill-dir>/scripts/cli.py stop
uv run --script <skill-dir>/scripts/cli.py stop --web

# Prune orphaned odoo-test containers
uv run --script <skill-dir>/scripts/cli.py prune
```

## Restore Seed Replica

```text
uv run --script <skill-dir>/scripts/cli.py db-restore <dump-path>.sql.gz <prodDB>_seed_<YYYYMMDD> --force
```

Restores a plain or gzip-compressed SQL dump into a pristine seed database and removes the copied `database.uuid` so Odoo issues a fresh one upon startup. SQL dumps omit the filestore; missing binary attachments or spreadsheet dashboards are expected and do not constitute bugs. Use `--force` to drop any existing database with the target name. Never run migrations or writes on the seed.

## Clone a Working Copy

```text
uv run --script <skill-dir>/scripts/cli.py db-clone <prodDB>_seed_<YYYYMMDD> <prodDB>_work_<YYYYMMDD> --force
```

Clones the database at the engine level using PostgreSQL `TEMPLATE` cloning, copies the local filestore directory if present, and clears the copied `database.uuid`. The operation terminates active sessions on source and target databases before cloning. If the working copy is broken by experiments or corrupted data, drop it and clone again from seed.

## Drop Database

```text
# Drop a disposable working copy
uv run --script <skill-dir>/scripts/cli.py db-drop <prodDB>_work_<YYYYMMDD> --force

# Dropping a seed database requires explicit confirmation flag
uv run --script <skill-dir>/scripts/cli.py db-drop <prodDB>_seed_<YYYYMMDD> --force --allow-seed
```

## Upgrade Rehearsal

Rehearse a module upgrade on a fresh working copy before it ships. Never touch the seed.

```text
# 1. Fresh working copy from the seed
uv run --script <skill-dir>/scripts/cli.py db-clone <prodDB>_seed_<YYYYMMDD> <prodDB>_work_<YYYYMMDD> --force

# 2. Upgrade the module with the new code: `test` runs Odoo with `-u <module> --stop-after-init` and the module's tests
uv run --script <skill-dir>/scripts/cli.py test <module> --db <prodDB>_work_<YYYYMMDD>

# 3. Verify results and data
uv run --script <skill-dir>/scripts/cli.py db-query --file <temp-dir>/check.sql --db <prodDB>_work_<YYYYMMDD> --json

# 4. Upgrade again and rerun the check: the output must match step 3
uv run --script <skill-dir>/scripts/cli.py test <module> --db <prodDB>_work_<YYYYMMDD>
uv run --script <skill-dir>/scripts/cli.py db-query --file <temp-dir>/check.sql --db <prodDB>_work_<YYYYMMDD> --json
```

`test` passes `-u` only for the target module, so the module must already be installed in the working copy; `dev` installs the profile's modules with `-i`. `test` refuses databases whose name contains `_seed_`. If any step fails, drop the working copy and clone it again from the seed:

```text
uv run --script <skill-dir>/scripts/cli.py db-drop <prodDB>_work_<YYYYMMDD> --force
uv run --script <skill-dir>/scripts/cli.py db-clone <prodDB>_seed_<YYYYMMDD> <prodDB>_work_<YYYYMMDD> --force
```

## One-Time Backfill During Upgrade

`noupdate="1"` data cannot carry an upgrade-time backfill: its `<function>` tags run only at install (see [Gotchas](gotchas.md)). Use a regular data file instead:

1. Add a data file without `noupdate` as the last entry of `data` in `__manifest__.py`, so it loads after every record it depends on.
2. In it, call a private model method: `<function model="res.partner" name="_backfill_example"/>`.
3. The method returns at once when an `ir.config_parameter` marker, such as `<module>.backfill_example_done`, is set. Otherwise it fixes the existing records, then sets the marker as its last step.

The data file runs on every upgrade, but the marker makes later upgrades skip the work and leaves records created after the backfill alone. Verify it with the [upgrade rehearsal](#upgrade-rehearsal): the second `-u` must change nothing.

## Tests That Need Committed Data

In a `TransactionCase`, `self.registry.cursor()` opens a new database cursor that sees only committed data, never the test's own records. `HttpCase` puts the registry in test mode, where `registry.cursor()` wraps the test cursor instead (`odoo/modules/registry.py`, `cursor`; `odoo/tests/common.py`, `HttpCase`). When a test reads through a second cursor and depends on data that must already exist in the database, call `self.skipTest("<reason>")` when that data is missing instead of failing on the environment.
