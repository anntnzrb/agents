# Runtime discovery

Read this reference when workspace or runtime discovery is ambiguous or fails.

This skill supports two local Odoo runtime families:

- **host runtime**: classic local install, especially Windows, with host PostgreSQL and `psql.exe`/`psql`.
- **Compose runtime**: Docker Compose Odoo stack with a PostgreSQL `db` service.

## Discovery goals

Resolve these values dynamically before acting:

- runtime backend
- workspace/runtime root
- `odoo.conf` path
- effective database name
- addon paths visible to the workspace
- DB execution path (`psql.exe`/`psql` or Compose `db` service)

## Compose runtime discovery

Use this order:

1. explicit `--runtime-dir`
2. `ODOO17_RUNTIME_DIR`
3. nearest ancestor/sibling named `odoo17` containing `docker-compose.yml`

A Compose runtime must contain:

- `docker-compose.yml`
- `config/odoo.conf`

Read `.env.example`, then `.env`, with `.env` taking precedence. Important variables:

- `ODOO17_CONFIG_DIR`
- `ODOO17_SOURCE_DIR`
- `ODOO17_CUSTOM_ADDONS_DIR`
- `POSTGRES_USER`
- `ODOO17_PROJECT_NAME`

Resolve relative env paths against the runtime root.

For the current macOS setup, addon paths are derived from:

- `${ODOO17_SOURCE_DIR}/odoo/addons`
- `${ODOO17_CUSTOM_ADDONS_DIR}`

DB queries execute through:

```bash
docker compose exec -T db psql -U <POSTGRES_USER> -d <db>
```

Prefer `docker compose`; fall back to `docker-compose`.

## Host workspace root

For host runtimes, start from the current working directory unless the user provides `--root`.

Walk upward first, but at each level also inspect immediate child directories for a real Odoo workspace. This lets invocations from an install root resolve `server/` automatically instead of assuming the caller already `cd`'d into `server/`.

Prefer the nearest directory that actually looks like an Odoo workspace, for example one that contains:

- `odoo.conf`
- `odoo-bin` plus addon directories

If `--root` is provided, treat it as the starting point and still validate that it resolves to a real workspace. Fail clearly if discovery cannot find one from the current location or its immediate descendants.

## Config discovery

Primary configuration source is `odoo.conf` discovered under the runtime/workspace root.

Parse it as the base runtime configuration, including at minimum:

- `db_host`
- `db_port`
- `db_user`
- `db_password` or password source metadata
- `db_name`
- `addons_path`
- `pg_path`

Do not assume `db_name` is set. If unresolved, report that. A Compose runtime may provide `ODOO17_DEFAULT_DB` as an explicit local fallback.

## Effective value precedence

Use this model when reporting runtime:

1. explicit public CLI flags
2. Compose runtime env
3. `odoo.conf`
4. `ODOO17_DEFAULT_DB` for an explicitly configured Compose runtime
5. unresolved

For inspection output, include provenance for each resolved value when practical, such as `source: compose-env` or `source: odoo-conf`.

## Addon discovery

For Compose runtimes, derive addon paths from `.env` bind mounts. For host runtimes, prefer addon paths from the resolved config. Normalize path separators and expand relative paths against the workspace root.

If addon paths are absent or incomplete, fall back to common workspace-relative directories only as best-effort inspection aid. Mark that fallback clearly rather than presenting it as authoritative.

## Database name resolution

Resolve the effective database name conservatively:

1. explicit `--db`
2. `odoo.conf` `db_name` if concrete and not false-like
3. Compose `ODOO17_DEFAULT_DB` when configured
4. unresolved

If unresolved, say so plainly instead of guessing.

## DB executable/service resolution

Host runtime:

1. explicit `--psql`
2. nearest `psql.exe`/`psql` reachable from discovered workspace or parents, including sibling `*/bin/psql.exe`
3. `pg_path` from resolved config
4. PATH lookup via `where.exe psql.exe` or `psql`
5. fail with clear trace

Compose runtime:

1. resolve Compose command (`docker compose`, then `docker-compose`)
2. use the Compose `db` service
3. fail clearly if Docker Compose is unavailable

## Path handling rules

- Use path-aware APIs, not ad-hoc string concatenation.
- Preserve original discovered paths in JSON output where useful.
- Do not hardcode machine-specific absolute paths into logic unless the user explicitly supplies them or they are documented as a final local fallback.

## Output expectations

Inspection commands should be JSON-first and explain:

- what runtime backend was discovered
- what config was used
- what remained unresolved
- source/provenance of important values

When discovery fails, fail specifically. Example: "Docker Compose not found" or "psql executable not found via explicit flag, nearby install-tree search, config pg_path, or PATH" is useful; "connection failed" without context is not.
