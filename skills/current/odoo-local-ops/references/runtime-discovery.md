# Runtime discovery

Use when workspace/runtime discovery is ambiguous or fails.

## Runtime families

- host runtime: classic local install, especially Windows; host PostgreSQL; `psql.exe`/`psql`
- Compose runtime: Docker Compose Odoo stack; PostgreSQL `db` service

## Discovery targets

Resolve dynamically before acting: runtime backend; workspace/runtime root; `odoo.conf` path; effective database name; workspace-visible addon paths; DB execution path (`psql.exe`/`psql` or Compose `db` service).

## Compose discovery

Runtime-dir precedence:
1. explicit `--runtime-dir`
2. `ODOO17_RUNTIME_DIR`
3. nearest ancestor/sibling named `odoo17` containing `docker-compose.yml`

Compose runtime requires `docker-compose.yml` and `config/odoo.conf`.

Read `.env.example`, then `.env`; `.env` wins. Important variables: `ODOO17_CONFIG_DIR`, `ODOO17_SOURCE_DIR`, `ODOO17_CUSTOM_ADDONS_DIR`, `POSTGRES_USER`, `ODOO17_PROJECT_NAME`. Resolve relative env paths against runtime root.

Current macOS addon paths:
- `${ODOO17_SOURCE_DIR}/odoo/addons`
- `${ODOO17_CUSTOM_ADDONS_DIR}`

DB queries:

```bash
docker compose exec -T db psql -U <POSTGRES_USER> -d <db>
```

Prefer `docker compose`; fall back to `docker-compose`.

## Host workspace root

Start at current working directory, unless `--root` is supplied. Walk upward; at each level also inspect immediate child directories for a real Odoo workspace, allowing install-root invocations to resolve `server/` without requiring `cd server/`.

Choose the nearest directory that actually resembles an Odoo workspace, e.g. containing `odoo.conf` or `odoo-bin` plus addon directories. With `--root`, use it as the starting point but still validate a real workspace. If none is found at the current location or immediate descendants, fail clearly.

## Configuration

Discover `odoo.conf` under the runtime/workspace root; parse it as base runtime configuration, including at minimum:

`db_host`, `db_port`, `db_user`, `db_password` or password source metadata, `db_name`, `addons_path`, `pg_path`.

Do not assume `db_name` exists; report unresolved. An explicitly configured Compose runtime may use `ODOO17_DEFAULT_DB` as a local fallback.

## Effective database

Precedence:
1. explicit public `--db`
2. concrete, non-false-like `odoo.conf` `db_name`
3. configured Compose `ODOO17_DEFAULT_DB`
4. unresolved

If unresolved, say so plainly; never guess. Inspection output should include provenance when practical, e.g. `source: odoo-conf` or `source: compose-env`.

## Addons

- Compose: derive addon paths from `.env` bind mounts.
- host: prefer resolved-config addon paths.

Normalize path separators and expand relative paths against workspace root. If paths are absent/incomplete, common workspace-relative directories are best-effort inspection aids only; mark fallback clearly, never as authoritative.

## DB executable/service

Host precedence:
1. explicit `--psql`
2. nearest `psql.exe`/`psql` reachable from discovered workspace or parents, including sibling `*/bin/psql.exe`
3. resolved-config `pg_path`
4. PATH lookup via `where.exe psql.exe` or `psql`
5. fail with a clear trace

Compose:
1. resolve Compose command: `docker compose`, then `docker-compose`
2. use Compose `db` service
3. fail clearly if Docker Compose is unavailable

## Path rules

Use path-aware APIs, not ad-hoc string concatenation. Preserve original discovered paths in JSON where useful. Do not hardcode machine-specific absolute paths unless explicitly supplied by the user or documented as a final local fallback.

## Inspection output and failures

Inspection commands are JSON-first and explain the discovered runtime backend, config used, unresolved values, and important-value source/provenance.

Failures must be specific. Useful examples: "Docker Compose not found"; "psql executable not found via explicit flag, nearby install-tree search, config pg_path, or PATH". "connection failed" without context is insufficient.
