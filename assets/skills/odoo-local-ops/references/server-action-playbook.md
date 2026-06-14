# Server Action production playbook

## When this applies

Server Actions created from the Odoo UI under Settings/Technical/Actions/Server Actions, using `state=code` / “Execute Python Code”. Treat production as the default environment and the default risk model.

## Hard rules

- Write every snippet to /tmp/<descriptive>.py before copying it; copy with pbcopy < /tmp/<descriptive>.py.
- Capture outputs with pbpaste > /tmp/<descriptive>_output.txt, then parse JSON into /tmp/<descriptive>_output.json.
- Read-only audits may end with raise UserError(payload_json); write success must never raise UserError.
- A write action succeeds by assigning action = {'type': 'ir.actions.client', 'tag': 'display_notification', ...}.
- A write action fails by raising UserError(...), intentionally rolling back the transaction.
- Do not use imports in safe_eval snippets unless the local Odoo source proves the opcode is allowed; default templates use zero imports.
- No env.cr.commit(), no rollback(), no sudo() unless the user explicitly requested bypassing normal access rules and the plan states why.
- Use IDs verified by audit, not display-name strings, for users/stages/programs/periods.

## Required workflow

1. `Source evidence`: read local code/report to identify the real fields used, e.g. report uses `lead.periodo_id` versus subfield `postgrado_id.periodo_ids`.
2. `Read-only audit`: use `search_count`, `read_group`, first/last ids, samples only when needed.
3. `Dry run`: expected counts, target distribution, references, exact failure shape.
4. `Execute`: ORM for small/business-logic writes; SQL set-based only for simple column updates that would freeze/timeout in UI.
5. `Postcheck`: rowcount, candidates touched, invariants.
6. `Final audit`: independent read-only audit plus DB hygiene checks for persistent temporary/staging leftovers.

## JSON helper

```python
# safe_eval-compatible JSON helpers: no imports, no json.dumps.
def esc(value):
    if value is None:
        return 'null'
    if value is False:
        return 'false'
    if value is True:
        return 'true'
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    text = text.replace('\\', '\\\\').replace('"', '\\"')
    text = text.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
    return '"' + text + '"'

def pair(key, value):
    return esc(key) + ':' + esc(value)

def obj(items):
    return '{' + ','.join(items) + '}'

def arr(values):
    return '[' + ','.join([esc(value) for value in values]) + ']'

def m2o(value):
    if not value:
        return 'null'
    return obj([pair('id', value[0]), pair('name', value[1])])

def group_obj(row, group_field):
    group_value = row.get(group_field)
    return obj([
        pair('key', group_value and group_value[0] or False),
        pair('label', group_value and group_value[1] or False),
        pair('count', row.get(group_field + '_count') or row.get('__count') or 0),
    ])
```

## Output policy

Compact JSON only. Do not export full records unless the user explicitly requested it. If record detail is needed, include first/last/sample with `limit`, never all rows.

## Failure policy

On any count mismatch, return JSON with `error`, `expected`, `actual`, `write_executed: false`, and do not write. If mismatch appears after write, raise `UserError` so Odoo rolls back. Because Odoo production is live, small deltas from newly created records are possible between audit/dry-run/execute; the template must distinguish `candidate_count_changed_before_write` from real post-write invariant failures and must either freeze candidates from the current transaction or abort with a diagnostic delta instead of guessing.

## Known failure lessons

- UserError after write rolls back, even when the modal says updated.
- SQL without active IS TRUE can update archived rows because UI/ORM active_test=True was omitted.
- ORM loops over thousands can freeze/reconnect the browser; use set-based SQL only after dry-run and only for simple column writes.
- active_domain from the current view can belong to another model; global export actions must use explicit domain = [].
- Large clipboard output is a design bug; compact output.
