# Server Action SQL safety

Sources:

- PostgreSQL `UPDATE`: `https://www.postgresql.org/docs/current/sql-update.html`
- PostgreSQL `CREATE TABLE` temp tables: `https://www.postgresql.org/docs/17/sql-createtable.html`
- PostgreSQL comparisons: `https://www.postgresql.org/docs/17/functions-comparison.html`
- PostgreSQL runtime config client timeouts: `https://www.postgresql.org/docs/17/runtime-config-client.html`

## Default preference

ORM first for small writes and any operation needing Odoo business logic, constraints, computed fields, mail tracking, onchanges, or access-rule semantics. SQL only for simple column updates after audit/dry-run when ORM/UI is likely to freeze or spam tracking.

## SQL direct-write checklist

- Explicit user asked for a write.
- Read-only audit passed.
- Dry-run passed with expected counts.
- SQL translates ORM domain fully, including `active IS TRUE` for UI/ORM active_test, M2M fields as `EXISTS`, nullable comparisons as `IS DISTINCT FROM`, and exact excluded ids.
- Values use `env.cr.execute(sql, params)`; identifiers are hardcoded/whitelisted only.
- `SET LOCAL lock_timeout = '5s'` and `SET LOCAL statement_timeout = '60s'` before mutating SQL unless the action is known tiny; if timeout fires, let exception rollback.
- Candidate table is `CREATE TEMP TABLE ... ON COMMIT DROP AS ...`.
- Candidate table has one row per target id; add `CREATE UNIQUE INDEX ... ON tmp_table(id)` or precheck `count(*) = count(DISTINCT id)` before `UPDATE ... FROM`.
- Update uses `UPDATE target SET ... FROM tmp_candidates WHERE target.id = tmp_candidates.id`.
- Postcheck validates exact rowcount, invariants, and zero wrong remaining rows for the frozen candidate set; final independent audits must also report live-domain deltas separately because new records may be created while the action is being prepared or executed.
- Success returns `display_notification`; failure raises `UserError`.

PostgreSQL warning: `UPDATE ... FROM` joins must produce at most one output row per target row, otherwise which join row updates the target is not readily predictable.

## Batch guidance

For very large/high-contention writes, use an idempotent batch template ordered by `id`; do not use `SKIP LOCKED` unless a final pass without `SKIP LOCKED` is included.

## Live-system concurrency guidance

Production domains are not static. Audit and dry-run totals are snapshots, not locks. Execute templates must freeze candidate IDs inside the write transaction and postcheck against those frozen candidates. If the live domain count changed since dry-run, the action must either abort before writing with `COUNT_CHANGED_BEFORE_WRITE` and a compact delta by stage/user/program/period, or explicitly proceed only after the user accepted the new total in a fresh dry-run. Never silently expand a previously approved write to new leads created after dry-run.

## Final hygiene SQL pattern

```sql
SELECT schemaname, tablename
FROM pg_tables
WHERE schemaname NOT LIKE 'pg_temp_%'
  AND tablename IN ('tmp_expected_name');
```
