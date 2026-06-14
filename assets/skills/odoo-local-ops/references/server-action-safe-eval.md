# Odoo Server Action safe_eval reference

Sources:

- Odoo docs `https://www.odoo.com/documentation/17.0/developer/reference/backend/actions.html`
- Odoo docs `https://www.odoo.com/documentation/17.0/applications/studio/automated_actions.html`
- Local source `/Users/Shared/odoo17/source/odoo-17.0+e.20260527/odoo/addons/base/models/ir_actions.py`, anchors `_run_action_code_multi` and `_get_eval_context`.

## Available names

- `env`
- `model`
- `record`
- `records`
- `time`
- `datetime`
- `dateutil`
- `timezone`
- `float_compare`
- `log`
- `_logger`
- `UserError`
- `Command`
- `uid`
- `user`

`record` and `records` may be `None`/empty unless context has matching `active_model` and `active_id(s)`. Global audit snippets must use `env['model.name']` explicitly.

Odoo captures result via the `action` variable. Local source `_run_action_code_multi` uses `safe_eval(..., mode='exec', nocopy=True)` then `return eval_context.get('action')`. Server Action snippets assign `action = {...}` and do not use `return`.

`log()` writes to `ir_logging` using an insert; strict read-only audits should avoid it and return JSON in `UserError` instead. `_logger.info()` writes server logs and is not the main audit output.

## Forbidden or avoided patterns

- no `import json`
- no `from odoo.exceptions import UserError`
- no dunder access such as `record.__dict__`
- no direct field assignment `record.field = value`; use `record.write({'field': value})`
- no `env.cr.commit()`/`rollback()`
- no `sudo()` by default

## Success and failure semantics

- Read-only audit can `raise UserError(payload_json)` because no writes should commit.
- Write success must set `action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {'type': 'success', 'title': '...', 'message': payload, 'sticky': True}}`.
- Write failure must `raise UserError(payload_json)` to abort and rollback.
