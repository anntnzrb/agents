# Runtime Discovery

Read before local development or database operations. Discovery identifies paths and configuration; it does not replace inspecting database contents.

## Local Paths

- Runtime: existing `ODOO_RUNTIME_PATH`, then `/opt/odoo17`, then `~/.local/share/odoo17`. If none exists, the resolver returns `/opt/odoo17` as fallback path.
- Custom addons: existing `ODOO_ADDONS_PATH`, then `./addons`, then the current repository root directory.
- Config: `<runtime>/config/odoo.conf`.
- Source addons: matching directories under `<runtime>/source` (resolved via `addons_paths`).

Use absolute environment paths when configuring overrides. The CLI does not provide `--root` or `--runtime-dir` command-line flags.

## Environment Inspection

```text
uv run --script <skill-dir>/scripts/cli.py env --json
```

`env --json` outputs key environment and database facts:
- `runtime_path`: location of installed Odoo core source.
- `addons_paths`: array of all active addon directories (core and enterprise).
- `custom_addons_path`: repository addons directory.
- `config_path`: path to active `odoo.conf`.
- `effective_database`: database resolved via precedence: `--db` CLI flag > `POSTGRES_DB` environment variable > profile default workflow database > `db_name` in `odoo.conf`.
- `database_source`: configuration source that resolved `effective_database` (`flag`, `env`, `profile`, or `odoo.conf`).
- `database_exists`: boolean indicating whether the effective database exists in PostgreSQL.
- `available_databases`: list of local databases present in PostgreSQL.

Always check `runtime_path` and `addons_paths` before designing new models or methods. Inspecting the installed source ensures your code builds upon native Odoo 17 conventions and primitives.

## Database Selection

Commands default to the database resolved by `env` (`effective_database`). You can override this default explicitly with `--db <database_name>`.

If the default database is missing, run `env --json` or `db-list` to locate available working replicas. Do not resort to raw psql or ad-hoc shell commands to guess database names.

## Container Health, Shell, and Lifecycle Management

Use the CLI subcommands to inspect and manage container state:

- `health [--port PORT] [--wait SECONDS]`: probes HTTP endpoint on `127.0.0.1` (never use `localhost` due to IPv6 binding conflicts). Use this command instead of invoking `curl` directly.
- `logs [-c web|db|test] [-f] [-n LINES]`: displays or tails logs from specific containers in the pod.
- `shell [script|-] [--file PATH] [--db DB] [--rollback]`: runs Python ORM code against the local replica (refuses `_seed_` and production). Requires `dev` to be running. Commits on exit unless `--rollback` is passed.
- `prune`: removes orphaned test containers (`odoo-test-*`) left behind after aborted test runs.
- `stop [--web]`: stops the pod or gracefully stops only the web container.

## Isolation and Multi-Agent Concurrency

The CLI manages container creation and unit test execution through an internal file lock (`odoo-ops.lock`). When multiple agents or tasks run tests concurrently, the CLI serializes execution automatically; external `flock` wrappers are unnecessary.

The test runner executes inside its own transient container (`odoo-test-*`) within the pod. It does not restart the pod or stop `odoo-web`, but it updates modules (`-u`) on the same database, so a running `dev` server can drop sessions or reload; run `health --wait 60` before browser checks. Test runs report `RESULT tests= failed= errors=`. Do not execute `git stash` while `dev` is actively running, as filesystem changes during Python autoreload cause server crashes.
