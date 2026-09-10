# Server Action SQL safety

Read [Safety model](safety-model.md) before production use. SQL bypasses ORM access rules, constraints, and tracking. Obtain explicit approval of that tradeoff and the exact targets and values.

Sources:

- PostgreSQL `UPDATE`: `https://www.postgresql.org/docs/current/sql-update.html`
- PostgreSQL `CREATE TABLE` temp tables: `https://www.postgresql.org/docs/17/sql-createtable.html`
- PostgreSQL comparisons: `https://www.postgresql.org/docs/17/functions-comparison.html`
- PostgreSQL runtime config client timeouts: `https://www.postgresql.org/docs/17/runtime-config-client.html`

## Default preference

ORM first for small writes and any operation needing Odoo business logic, constraints, computed fields, mail tracking, onchanges, or access-rule semantics. SQL only for simple column updates after audit/dry-run when ORM/UI is likely to freeze or spam tracking.

## SQL direct-write checklist

- User approved the rendered SQL action, exact IDs, values, exclusions, and expected effects; set `WRITE_APPROVED = True` only after that approval
- Read-only audit passed
- Dry-run passed with expected counts
- SQL translates ORM domain fully, including `active IS TRUE` for UI/ORM active_test, M2M fields as `EXISTS`, nullable comparisons as `IS DISTINCT FROM`, and exact excluded ids
- Values use `env.cr.execute(sql, params)`; identifiers are hardcoded/whitelisted only
- `SET LOCAL lock_timeout = '5s'` and `SET LOCAL statement_timeout = '60s'` before mutating SQL unless the action is known tiny; if timeout fires, let exception rollback
- Candidate table is `CREATE TEMP TABLE ... ON COMMIT DROP AS ...`
- Never drop an existing table to clear a name collision. Create a new temporary candidate table and refer to it through `pg_temp`; abort on a collision.
- Candidate table has one row per target id; add `CREATE UNIQUE INDEX ... ON tmp_table(id)` or precheck `count(*) = count(DISTINCT id)` before `UPDATE ... FROM`
- Update uses `UPDATE target SET ... FROM tmp_candidates WHERE target.id = tmp_candidates.id`
- Postcheck validates exact rowcount, invariants, and zero wrong remaining rows for the frozen candidate set; final independent audits must also report live-domain deltas separately because new records may be created while the action is being prepared or executed
- Success returns `display_notification`; failure raises `UserError`

PostgreSQL warning: `UPDATE ... FROM` joins must produce at most one output row per target row, otherwise which join row updates the target is not readily predictable.

## Batch guidance

For very large/high-contention writes, use an idempotent batch template ordered by `id`; do not use `SKIP LOCKED` unless a final pass without `SKIP LOCKED` is included.

## Live-system concurrency guidance

Production domains are not static. Audit and dry-run totals are snapshots, not locks. Bind candidates to the exact approved IDs and verify identity as well as count before writing. Freeze candidates inside the write transaction and postcheck that set. Abort on changed IDs or preconditions, even if the total is unchanged. A changed total requires a fresh preview and user approval, not an automatic adjustment. Use row locks or conditional predicates where concurrent changes could invalidate the approved values.

## Final hygiene SQL pattern

```sql
SELECT schemaname, tablename
FROM pg_tables
WHERE schemaname NOT LIKE 'pg_temp_%'
  AND tablename IN ('tmp_expected_name');
```
