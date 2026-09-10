# Database recipes

Use these commands only for the confirmed disposable local replica. Read [Runtime discovery](runtime-discovery.md) and [Safety model](safety-model.md) first.

## Inspect the replica

```text
uv run --script <skill-dir>/scripts/cli.py db-summary --db local-replica --json
uv run --script <skill-dir>/scripts/cli.py db-tables --db local-replica --limit 20 --json
uv run --script <skill-dir>/scripts/cli.py db-query 'SELECT current_database()' --db local-replica
```

Queries run through `podman exec` and `psql` in the configured local database container. These commands can initialize the local Podman runtime. Non-`--unsafe` queries use a read-only transaction; this is not a sandbox for untrusted SQL or external functions.

## Rebuild a replica

```text
uv run --script <skill-dir>/scripts/cli.py db-clone local-master local-replica --force
```

This executes immediately. There is no dry-run flag. `--force` drops an existing target. Source and target must differ. The clone disconnects sessions on both databases; it does not run Odoo modules or tests. Keep the source as a local master copy, not a production database.

Use `db-query --unsafe` for intentional destructive SQL on the disposable replica. Never treat that flag as permission for remote or production operations.
