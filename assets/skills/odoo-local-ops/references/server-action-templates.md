# Server Action template catalog

Templates are starting points: copy to `<temp-dir>/<task>.py`, edit there, then use the platform clipboard command.

## Templates

Shared required placeholders — `model name`, `domain`, `expected counts`, `target ids`, `excluded ids`, `fields to update`, `final invariant checks` — apply to:

- `templates/server_action_audit_readonly.py.tmpl`: read-only audit; ends with `raise UserError(payload)`.
- `templates/server_action_dry_run.py.tmpl`: no-write validation of target counts/distribution and JSON output before approval.
- `templates/server_action_execute_orm_small.py.tmpl`: small ORM writes requiring Odoo business logic; success via `action = display_notification`.
- `templates/server_action_execute_sql_set_based.py.tmpl`: simple massive column writes; temp candidates + SQL pre/postcheck.
- `templates/server_action_final_audit.py.tmpl`: independent closeout audit; no writes; checks invariants and persistent leftovers.
- `templates/server_action_clipboard_workflow.md.tmpl`: macOS workflow reminder for `<temp-dir>`, `pbcopy`, `pbpaste`, and JSON parsing.

`templates/server_action_contextual_selection_audit.py.tmpl`: read-only contextual action launched from the list/form Action menu; validates `active_model`, resolves only selected `active_ids`, rejects empty or oversized selection, and returns compact JSON. Required placeholders: `model name`, `purpose`, `maximum selection size`, `sample limit`, `sample fields`, `grouping fields`, optional narrowing domain.

`templates/server_action_modern_python_gauntlet_crm_lead.py.tmpl`: after an Odoo/Python runtime or image change, re-checks the production `safe_eval` surface on `crm.lead`. Performs 43 read-only checks covering modern Python 3.10 syntax, functional helpers, wrappers, bounded ORM operations, and explicitly reports excluded unsafe constructs. Run on at most 1000 selected leads; compare returned counts with the known 43/43 baseline.
