# Database recipes

Use these commands only for the confirmed disposable local replica. Read [Runtime discovery](runtime-discovery.md) and [Safety model](safety-model.md) first.

Naming convention: `<prod-name>_seed_<YYYYMMDD>` for the untouched replica
(restored once per DBA dump) and `<prod-name>_work_<YYYYMMDD>` for the
throwaway working copy. Lowercase with underscores only; never hyphens,
which force quoting in PostgreSQL identifiers.

## Inspect the replica

```text
uv run --script <skill-dir>/scripts/cli.py db-summary --db <prod-name>_work_<YYYYMMDD> --json
uv run --script <skill-dir>/scripts/cli.py db-tables --db <prod-name>_work_<YYYYMMDD> --limit 20 --json
uv run --script <skill-dir>/scripts/cli.py db-query 'SELECT current_database()' --db <prod-name>_work_<YYYYMMDD>
```

Queries run through `podman exec` and `psql` in the configured local database container. These commands can initialize the local Podman runtime. Non-`--unsafe` queries use a read-only transaction; this is not a sandbox for untrusted SQL or external functions.

## Restore the seed replica

```text
uv run --script <skill-dir>/scripts/cli.py db-restore <dump-path>.sql.gz <prod-name>_seed_<YYYYMMDD> --force
```

Restores a plain or gzip-compressed SQL dump into a fresh database and drops the
copied `database.uuid` so Odoo issues a new one on next load. A SQL dump carries
no filestore, so attachments will not resolve in the restored replica; this is
expected, not a code bug. Neutralization and data masking happen before the dump
reaches this runtime. Use `--force` to drop an existing target first; without it
the command refuses to overwrite.

## Clone a working copy

```text
uv run --script <skill-dir>/scripts/cli.py db-clone <prod-name>_seed_<YYYYMMDD> <prod-name>_work_<YYYYMMDD> --force
```

This copies the database engine-side with `CREATE DATABASE ... WITH TEMPLATE`,
then copies the filestore directory and drops the copied `database.uuid` so the
clone gets a fresh identity (mirroring what `odoo db duplicate` does). With no
source filestore it warns instead of failing; that replica simply cannot serve
attachments. Use `--force` to drop an existing target. This executes
immediately. There is no dry-run flag. Source and target must differ. The clone
disconnects sessions on both databases; it does not run Odoo modules or tests.
Keep the seed as an untouched copy; do all work in the clone.

Use `db-query --unsafe` for intentional destructive SQL on the disposable replica. Never treat that flag as permission for remote or production operations.
