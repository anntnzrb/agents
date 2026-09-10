# Server Action template catalog

Templates are starting points: copy to `<temp-dir>/<task>.py`, edit there, then use the platform clipboard command.

Read [Safety model](safety-model.md) before production use. Render every placeholder and review the full result locally. Preparing or copying code is not permission to save or run it in production. Do not use templates to bypass JSON-RPC consent.

Both write templates default to `WRITE_APPROVED = False`. Set it to `True` only after explicit approval of the rendered action, exact target IDs, values, and expected effects. Never substitute a matching count for target identity. Rehearse on the disposable replica with outbound integrations disabled.

`target_ids_literal` contains the exact approved records, excluding `excluded_ids_literal`; write templates reject empty, duplicate, invalid, or overlapping targets. `expected_to_update` must match that ID set. A discovery dry-run may use empty targets to inspect a domain, but that result cannot authorize a write until exact IDs are captured and approved.

The ORM template verifies that frozen targets no longer match the correction predicate. Supply predicates that express the defect, not just a broad selection. It does not replace task-specific value invariants or concurrency control.

The final audit's `expected_distribution_literal` uses `{field_name: {group_key: count}}`, with native Python keys such as integer many-to-one IDs. The mapping must cover the configured grouping fields and all expected buckets. Use `{}` only when no distribution invariant is required.

## Templates

Shared required placeholders; `model name`, `domain`, `expected counts`, `target ids`, `excluded ids`, `fields to update`, `final invariant checks`; apply to:

- `templates/server_action_audit_readonly.py.tmpl`: read-only audit; ends with `raise UserError(payload)`.
- `templates/server_action_dry_run.py.tmpl`: no-write validation of target counts/distribution and JSON output before approval.
- `templates/server_action_execute_orm_small.py.tmpl`: small ORM writes requiring Odoo business logic; success via `action = display_notification`.
- `templates/server_action_execute_sql_set_based.py.tmpl`: simple massive column writes; temp candidates + SQL pre/postcheck.
- `templates/server_action_final_audit.py.tmpl`: independent closeout audit; no writes; checks invariants and persistent leftovers.
- `templates/server_action_clipboard_workflow.md.tmpl`: macOS workflow reminder for `<temp-dir>`, `pbcopy`, `pbpaste`, and JSON parsing.

`templates/server_action_contextual_selection_audit.py.tmpl`: read-only contextual action launched from the list/form Action menu; validates `active_model`, resolves only selected `active_ids`, rejects empty or oversized selection, and returns compact JSON. Required placeholders: `model name`, `purpose`, `maximum selection size`, `sample limit`, `sample fields`, `grouping fields`, optional narrowing domain.

`templates/server_action_modern_python_gauntlet_crm_lead.py.tmpl`: after an Odoo/Python runtime or image change, re-checks the production `safe_eval` surface on `crm.lead`. Performs 43 read-only checks covering modern Python 3.10 syntax, functional helpers, wrappers, bounded ORM operations, and explicitly reports excluded unsafe constructs. Run on at most 1000 selected leads; compare returned counts with the known 43/43 baseline.
