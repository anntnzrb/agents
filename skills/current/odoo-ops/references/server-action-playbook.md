# Server Action production playbook

## When this applies

Server Actions created from the Odoo UI under Settings/Technical/Actions/Server Actions, using `state=code` / “Execute Python Code”. Treat production as the default environment and the default risk model.

Read [Safety model](safety-model.md) first. Preparing a snippet locally does not authorize production interaction. Ask before production reads; obtain separate approval before creating, saving, or executing a mutating action. Never substitute UI actions for unapproved JSON-RPC.

## Hard rules

- Write every snippet to `<temp-dir>/<descriptive>.py` before copying it; copy with `pbcopy < <temp-dir>/<descriptive>.py` on macOS
- Capture outputs with `pbpaste > <temp-dir>/<descriptive>_output.txt` on macOS, then parse JSON into `<temp-dir>/<descriptive>_output.json`
- Read-only audits may end with raise UserError(payload_json); write success must never raise UserError
- A write action succeeds by assigning action = {'type': 'ir.actions.client', 'tag': 'display_notification', ...}
- A write action fails by raising UserError(...), intentionally rolling back the transaction
- Do not use imports in safe_eval snippets unless the local Odoo source proves the opcode is allowed; default templates use zero imports
- Never call `env.cr.commit()` or `rollback()` in these templates. Never use `sudo()` unless the user explicitly approves bypassing access rules and the plan states why.
- Use IDs verified by audit, not display-name strings, for users/stages/programs/periods

## Required workflow

1. `Source evidence`: read local code/report to identify the real fields used, e.g. report uses `lead.periodo_id` versus subfield `postgrado_id.periodo_ids`
2. `Read-only audit`: use `search_count`, `read_group`, first/last ids, samples only when needed
3. `Dry run`: exact target and excluded IDs, expected counts, values, preconditions, distribution, and expected side effects
4. `Approval and execute`: obtain user approval of the rendered operation and exact scope, then set `WRITE_APPROVED = True`. Use ORM for small/business-logic writes; direct SQL requires approval of its bypassed ORM behavior.
5. `Postcheck`: rowcount, candidates touched, invariants
6. `Final audit`: independent read-only audit plus DB hygiene checks for persistent temporary/staging leftovers

## JSON helper

Use the import-free JSON helpers in the [template catalog](server-action-templates.md). Preserve escaped control characters and quoted object keys. Parse sample output locally before deploying the action.

## Output policy

Compact JSON only. Do not export full records unless the user explicitly requested it. If record detail is needed, include first/last/sample with `limit`, never all rows.

## Failure policy

On any pre-write count, identity, or precondition mismatch, return JSON with `error`, `expected`, `actual`, `write_executed: false`, and do not write. Post-write invariant failures must raise `UserError` to roll back the current transaction. Freeze exact approved IDs and distinguish live-domain deltas from failures on that set. Rollback cannot undo external effects, separate commits, email, or webhooks. Do not rerun an ambiguous operation until approved reads establish what happened.

## Known failure lessons

- UserError after write rolls back, even when the modal says updated
- SQL without active IS TRUE can update archived rows because UI/ORM active_test=True was omitted
- ORM loops over thousands can freeze/reconnect the browser; use set-based SQL only after dry-run and only for simple column writes
- active_domain from the current view can belong to another model; global export actions must use explicit domain = []
- Large clipboard output is a design bug; compact output
