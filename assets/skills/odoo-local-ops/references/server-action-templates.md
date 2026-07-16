# Server Action template catalog

Templates are starting points; copy to `/tmp/<task>.py`, edit there, then `pbcopy < /tmp/<task>.py`.

## Templates

### `templates/server_action_audit_readonly.py.tmpl`

Use for read-only audit; ends with `raise UserError(payload)`.

Required placeholders: model name, domain, expected counts, target ids, excluded ids, fields to update, final invariant checks.

### `templates/server_action_contextual_selection_audit.py.tmpl`

Use for a read-only contextual action launched from the list/form Action menu. It validates `active_model`, resolves only the selected `active_ids`, rejects an empty or oversized selection, and returns compact JSON.

Required placeholders: model name, purpose, maximum selection size, sample limit, sample fields, grouping fields, and an optional narrowing domain.

### `templates/server_action_dry_run.py.tmpl`

Use for no-write validation of target counts/distribution and JSON output before approval.

Required placeholders: model name, domain, expected counts, target ids, excluded ids, fields to update, final invariant checks.

### `templates/server_action_execute_orm_small.py.tmpl`

Use for small ORM writes that need Odoo business logic; success via `action = display_notification`.

Required placeholders: model name, domain, expected counts, target ids, excluded ids, fields to update, final invariant checks.

### `templates/server_action_execute_sql_set_based.py.tmpl`

Use for simple massive column writes; temp candidates + SQL pre/postcheck.

Required placeholders: model name, domain, expected counts, target ids, excluded ids, fields to update, final invariant checks.

### `templates/server_action_final_audit.py.tmpl`

Use for independent closeout audit; no writes; checks invariants and persistent leftovers.

Required placeholders: model name, domain, expected counts, target ids, excluded ids, fields to update, final invariant checks.

### `templates/server_action_clipboard_workflow.md.tmpl`

Use as a local workflow reminder for `/tmp`, `pbcopy`, `pbpaste`, JSON parsing.

Required placeholders: model name, domain, expected counts, target ids, excluded ids, fields to update, final invariant checks.
