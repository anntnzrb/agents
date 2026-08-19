# Odoo Server Action safe_eval reference

Sources:
- Odoo docs `https://www.odoo.com/documentation/17.0/developer/reference/backend/actions.html`
- Odoo docs `https://www.odoo.com/documentation/17.0/applications/studio/automated_actions.html`
- Local `<odoo-source>/odoo/addons/base/models/ir_actions.py`: `_run_action_code_multi`, `_get_eval_context`
- Odoo 17 upstream `odoo/tools/safe_eval.py`: `_SAFE_OPCODES`, `_BUILTINS`

## Production profile

Audited deployment: Odoo 17 + Python 3.10. Deployment fact, not universal Odoo 17 guarantee; re-audit after changing Odoo image or Python runtime.

Production gauntlet: 43/43 checks, `write_executed: false`, model `crm.lead`. This confirmed execution, not merely opcode compatibility, of: function annotations; import-free decorator without closure; positional-only and keyword-only arguments; generator functions/expressions; list/dict/set comprehensions; `map`, `filter`, `reduce`; higher-order pipeline; literal `match`; simple walrus; dict merge; self-documenting f-strings; ordered set-backed deduplication; Odoo recordset operations; `search_count`; `read_group`.

Syntax requires both: (1) Python 3.10 compilation; (2) every generated opcode, including nested functions, comprehensions, lambdas, and generators, in Odoo `_SAFE_OPCODES`.

Installed packages are not automatically usable: imports blocked; Server Actions see only Odoo-injected names and restricted built-ins.

## Available names

`env`, `model`, `record`, `records`, `time`, `datetime`, `dateutil`, `timezone`, `float_compare`, `log`, `_logger`, `UserError`, `Command`, `uid`, `user`, `b64encode`, `b64decode`.

Production-confirmed restricted functional built-ins: `map`, `filter`, `reduce`, `sorted`, `zip`, `enumerate`, `sum`, `min`, `max`, `all`, `any`, `set`, `range`. `reduce` injected directly; `functools` and `itertools` not importable.

## Python 3.10 under safe_eval

- Small local helper without closure: supported; prefer named pure helpers for repeated transformations.
- Function parameter/return annotations using visible built-ins: production-confirmed; use sparingly for helper contracts; UI has no static checker.
- Variable annotation: forbidden; emits `SETUP_ANNOTATIONS`.
- List/dict/set comprehension: production-confirmed; single-purpose and bounded.
- Generator function/expression: production-confirmed; useful with `sum`, `all`, `any`; NEVER hide ORM queries inside.
- `map`/`filter`/`reduce`: production-confirmed; prefer comprehension, `sum`, or clearer explicit loop; `reduce` MUST have initializer.
- Ordered deduplication with `set` + `list`: production-confirmed; set gives O(1) membership, list preserves order.
- Import-free decorator without closure: production-confirmed; only for a real local contract; imported and closure-producing decorators unavailable.
- Simple walrus: production-confirmed; use only when it removes duplicate work without obscuring control flow.
- Walrus in module-scope comprehension: forbidden; may emit blacklisted `STORE_GLOBAL`.
- Dict merge `left|right`: production-confirmed; small copy-on-write dictionaries, not record mutation.
- Self-documenting f-string: production-confirmed; useful for diagnostics, but compact JSON remains audit-output contract.
- `match` on scalar literals plus wildcard: production-confirmed; use only when clearer than `if/elif`.
- Sequence, mapping, or class structural patterns: forbidden; emit unsupported `MATCH_*`/`GET_LEN` opcodes.
- Closure capturing outer local: forbidden; emits unsupported `LOAD_CLOSURE`/`LOAD_DEREF`; pass values explicitly.
- Specific `try/except`: supported; catch only errors the snippet can handle; NEVER turn unknown failure into `ok`.
- `with`: forbidden in audited allowlist; do not build transaction/context-manager patterns inside snippets.

Functional-first ≠ abstraction-first. Keep selection, ORM reads, writes, logging, and action return in an explicit imperative shell; use pure helpers/bounded comprehensions only for in-memory transformations. For ORM data, prefer vectorized recordset methods, `search_count`, and `read_group` over Python-level iteration.

Literal `match` only for genuine scalar dispatch:

```python
match OUTPUT_MODE:
    case 'audit':
        output_kind = 'json'
    case 'open_records':
        output_kind = 'window_action'
    case _:
        raise UserError('unsupported_output_mode')
```

Do not turn a two-branch boolean check into `match`; modern-looking ceremony is not an improvement.

`record`/`records` may be `None`/empty unless context has matching `active_model` and `active_id(s)`. Global audit snippets MUST use `env['model.name']` explicitly.

Odoo captures result through `action`: local `_run_action_code_multi` calls `safe_eval(..., mode='exec', nocopy=True)` then `return eval_context.get('action')`. Server Action snippets assign `action = {...}`; they do not use `return`.

`log()` inserts into `ir_logging`; strict read-only audits should avoid it and return JSON in `UserError` instead. `_logger.info()` writes server logs, not the main audit output.

## Forbidden or avoided

- no `import json`
- no `from odoo.exceptions import UserError`
- no dunder access, e.g. `record.__dict__`
- no direct field assignment `record.field = value`; use `record.write({'field': value})`
- no `env.cr.commit()`/`rollback()`
- no `sudo()` by default
- no structural `match` patterns, closures, or context-manager syntax

## Success/failure semantics

- Read-only audit can `raise UserError(payload_json)`; no writes should commit.
- Write success MUST set `action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {'type': 'success', 'title': '...', 'message': payload, 'sticky': True}}`.
- Write failure MUST `raise UserError(payload_json)` to abort and rollback.
