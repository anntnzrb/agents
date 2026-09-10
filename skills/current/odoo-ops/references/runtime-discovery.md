# Runtime discovery

Read before local development or database operations. Discovery finds paths; it does not certify a disposable database.

## Local paths

- Runtime: existing `ODOO_RUNTIME_PATH`, then `/opt/odoo17`, then `~/.local/share/odoo17`. If none exists, the resolver returns `/opt/odoo17` as its fallback path.
- Custom addons: existing `ODOO_ADDONS_PATH`, then `~/repos/etech/odoo/addons`, then `./addons`, then the current directory.
- Config: `<runtime>/config/odoo.conf`.
- Source addons: matching directories under `<runtime>/source`.

Use absolute environment paths. The CLI does not provide `--root` or `--runtime-dir` overrides.

## Database selection

Database inspection commands use `--db` when supplied, otherwise the resolved config's `options.db_name`, falling back to `ODOO_DB_NAME` or the controller's default. Development and test commands select their database through the requested workflow or module resolution. Workflow settings live in `profiles/<profile>.json`.

```text
uv run --script <skill-dir>/scripts/cli.py env --json
```

Inspect `runtime_path`, `config_path`, `custom_addons_path`, `effective_database`, and the requested workflow before destructive work. `env` reports configuration, not a proof that the database is connected or disposable.

## Isolation

Keep Podman pointed at the local host or local Podman machine. Never use production container connections for replica commands. Loopback connections can still be tunnels; verify their purpose locally.

Disable copied production cron jobs and outbound integrations before running application code. Missing local data never authorizes JSON-RPC discovery; follow [Safety model](safety-model.md).
