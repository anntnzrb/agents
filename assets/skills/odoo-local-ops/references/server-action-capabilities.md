# Odoo 17 Server Action capability map

Use this reference when the user asks what Server Actions can do, wants a contextual or automated action, or is deciding between UI Python, automation, cron, webhook, JSON-RPC, and a custom module.

Sources:

- Odoo 17 developer actions reference: `https://www.odoo.com/documentation/17.0/developer/reference/backend/actions.html`
- Odoo 17 Studio automation reference: `https://www.odoo.com/documentation/17.0/applications/studio/automated_actions.html`
- Local Odoo 17 source: `odoo/addons/base/models/ir_actions.py` and `odoo/addons/base_automation/models/base_automation.py`

## Decision map

| Need | Prefer | Why |
| --- | --- | --- |
| Audit or repair selected records manually | Contextual Server Action | Appears in the list/form Action menu and receives `active_model` plus `active_ids`. |
| One-off global audit or gated cleanup | Execute Python Code Server Action | Works without external credentials and stays inside the Odoo transaction. |
| React to create/write/delete/stage/tag changes | Automation Rule | Odoo supplies the trigger and record context; restrict trigger fields to avoid duplicate executions. |
| Run work periodically | Scheduled Action | Use a small batch and idempotent cursor/domain; do not make a browser-triggered action wait. |
| Compose existing UI actions | Execute Existing Actions (`multi`) | Child actions run by sequence and the last returned action becomes the client result. |
| Notify an external system | Outgoing webhook action | Prefer field allowlists and non-secret payloads; treat the destination URL as sensitive configuration. |
| Receive an external event | Automation Rule with webhook trigger | The generated URL is a secret. Validate the `payload`, use a narrow target-record resolver, and rotate the secret if exposed. |
| Reusable business logic, complex workflows, tests, or stable API | Custom addon method | Server Action code is operational glue, not a maintainable application layer. |
| External integration without administrator/API credentials | Do not use JSON-RPC | Keep the workflow inside Odoo; never request or paste API keys merely to bypass missing permissions. |

## Server Action types in Odoo 17

Local `ir.actions.server.state` supports:

- `code`: Execute Python Code.
- `object_create`: Create Record.
- `object_write`: Update Record.
- `webhook`: Send Webhook Notification.
- `multi`: Execute Existing Actions.

For code actions, `action = {...}` is the only supported return channel. For `multi`, actions run by `sequence`; the last non-empty returned action is used.

## Contextual actions

Use **Create Contextual Action** to bind the Server Action to its model. Odoo sets `binding_model_id` and exposes it in list/form Action menus. The default binding view types are `list,form`.

Treat UI context as untrusted input:

- Require `env.context.get('active_model') == '<expected.model>'`.
- Resolve `active_ids` explicitly and call `.exists()`.
- For a global action, ignore inherited `active_domain` and use an explicit domain.
- For a selected-record action, never silently expand beyond `active_ids`.
- Cap selection size before expensive reads or writes.

Use `templates/server_action_contextual_selection_audit.py.tmpl` as the read-only starting point.

## Automation rules

Odoo 17 supports triggers including stage/user/tag/state/priority changes, archive/unarchive, save, delete, UI change, date-based execution, and webhooks.

- Specify trigger fields for save/UI-change rules; otherwise the action can run repeatedly on unrelated writes.
- Make trigger code idempotent because retries, repeated saves, and overlapping conditions are normal.
- `record` and `records` can be empty. Webhook-triggered code additionally receives `payload`.
- Avoid recursive writes to trigger fields. If unavoidable, add a context guard and a final invariant test.
- `On UI change` is manual-form behavior, not a general write hook.

## Safe useful patterns

- **Preview then apply**: one read-only contextual action reports the selected IDs/counts; a separate write action requires the approved count.
- **Return a filtered window**: assign an `ir.actions.act_window` dictionary after audit so the user can inspect the exact recordset instead of exporting it.
- **Chain small actions**: use `multi` for independently understandable steps; do not hide a large workflow in a chain of opaque snippets.
- **Queue by flag**: a Server Action marks a bounded recordset for later processing; a scheduled/module method performs heavy work. Prefer an addon when this becomes permanent.
- **Webhook notification**: send only allowlisted identifiers/state, never credentials, access tokens, binary fields, chatter bodies, or unrestricted `read()` payloads.

## Escalate to an addon when

- The snippet needs imports unavailable to `safe_eval`.
- Logic is reused by more than one action or depends on more than a few models.
- Correctness requires unit tests, access-rule tests, retries, queues, or observability.
- The operation is long-running, calls multiple external systems, or needs secrets.
- A schema change, computed field, constraint, controller, or stable API is required.

In those cases, put tested logic in a model method and keep the Server Action to one explicit method call.
