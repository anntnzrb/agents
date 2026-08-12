# Odoo 17 Server Action capability map

Use when choosing Server Actions, contextual/automated actions, UI Python, automation, cron, webhooks, JSON-RPC, or a custom module.

Sources:
- Odoo actions: `https://www.odoo.com/documentation/17.0/developer/reference/backend/actions.html`
- Studio automation: `https://www.odoo.com/documentation/17.0/applications/studio/automated_actions.html`
- Local: `odoo/addons/base/models/ir_actions.py`; `odoo/addons/base_automation/models/base_automation.py`

## Choose

- Selected-record manual audit/repair → Contextual Server Action; list/form Action menu, `active_model` + `active_ids`.
- One-off global audit/gated cleanup → Execute Python Code Server Action; no external credentials, inside Odoo transaction.
- Create/write/delete or stage/tag changes → Automation Rule; supplied trigger/context; restrict trigger fields to prevent duplicate runs.
- Periodic work → Scheduled Action; small batch, idempotent cursor/domain; NEVER make browser-triggered work wait.
- Compose UI actions → Execute Existing Actions (`multi`); children run by `sequence`; last returned action becomes client result.
- Notify external system → Outgoing webhook action; field allowlist, non-secret payload; destination URL is sensitive configuration.
- Receive external event → Automation Rule with webhook trigger; generated URL is secret; validate `payload`, use narrow target-record resolver, rotate exposed secret.
- Reusable logic, complex workflow, tests, or stable API → Custom addon method; Server Action code is operational glue, not application layer.
- External integration without administrator/API credentials → NEVER use JSON-RPC; keep workflow in Odoo; NEVER request or paste API keys to bypass missing permissions.

## Server Action types

Local `ir.actions.server.state` supports:
- `code`: Execute Python Code
- `object_create`: Create Record
- `object_write`: Update Record
- `webhook`: Send Webhook Notification
- `multi`: Execute Existing Actions

Code action return channel: `action = {...}` only. `multi`: sequence order; last non-empty returned action is used.

## Contextual actions

**Create Contextual Action** binds a Server Action to its model. Odoo sets `binding_model_id` and exposes it in list/form Action menus. Default binding view types: `list,form`.

UI context is untrusted:
- MUST require `env.context.get('active_model') == '<expected.model>'`.
- Resolve `active_ids` explicitly; call `.exists()`.
- Global action: ignore inherited `active_domain`; use explicit domain.
- Selected-record action: NEVER silently expand beyond `active_ids`.
- Cap selection size before expensive reads/writes.

Read-only starting point: `templates/server_action_contextual_selection_audit.py.tmpl`.

## Automation rules

Triggers include stage/user/tag/state/priority changes, archive/unarchive, save, delete, UI change, date-based execution, and webhooks.

- Specify trigger fields for save/UI-change rules; otherwise unrelated writes can retrigger the action.
- Make trigger code idempotent; retries, repeated saves, and overlapping conditions are normal.
- `record` and `records` can be empty; webhook code additionally receives `payload`.
- Avoid recursive writes to trigger fields. If unavoidable, add a context guard and final invariant test.
- `On UI change` is manual-form behavior, not a general write hook.

## Safe patterns

- Preview/apply: read-only contextual action reports selected IDs/counts; separate write action requires approved count.
- Filtered window: after audit, assign an `ir.actions.act_window` dictionary so users inspect the exact recordset instead of exporting it.
- Small chains: use `multi` for independently understandable steps; NEVER hide a large workflow in opaque snippets.
- Queue by flag: Server Action marks a bounded recordset; scheduled/module method performs heavy work. Prefer an addon when permanent.
- Webhook notification: send only allowlisted identifiers/state; NEVER send credentials, access tokens, binary fields, chatter bodies, or unrestricted `read()` payloads.

## Escalate to an addon

Do so when the snippet needs imports unavailable to `safe_eval`; logic is reused by multiple actions or depends on more than a few models; correctness needs unit/access-rule tests, retries, queues, or observability; work is long-running, calls multiple external systems, or needs secrets; or a schema change, computed field, constraint, controller, or stable API is required.

Put tested logic in a model method; keep the Server Action to one explicit method call.
