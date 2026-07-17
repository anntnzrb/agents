# Odoo Server Action safe_eval reference

Sources:

- Odoo docs `https://www.odoo.com/documentation/17.0/developer/reference/backend/actions.html`
- Odoo docs `https://www.odoo.com/documentation/17.0/applications/studio/automated_actions.html`
- Local source `<odoo-source>/odoo/addons/base/models/ir_actions.py`, anchors `_run_action_code_multi` and `_get_eval_context`.
- Odoo 17 upstream `odoo/tools/safe_eval.py`, especially `_SAFE_OPCODES` and `_BUILTINS`.

## Known production runtime profile

The audited production deployment uses Odoo 17 on Python 3.10. Treat that as a
deployment fact, not a universal Odoo 17 guarantee. Re-run the capability audit
after changing the Odoo image or Python runtime.

The production gauntlet completed 43/43 checks with `write_executed: false` on
`crm.lead`. This confirmed actual execution—not merely opcode compatibility—of
function annotations, an import-free decorator without closure, positional-only
and keyword-only arguments, generator functions and expressions, list/dict/set
comprehensions, `map`, `filter`, `reduce`, a higher-order pipeline, literal
`match`, simple walrus, dict merge, self-documenting f-strings, ordered set-backed
deduplication, Odoo recordset operations, `search_count`, and `read_group`.

Python syntax support has two gates:

1. The construct must compile on Python 3.10.
2. Every generated opcode, including opcodes inside nested functions,
   comprehensions, lambdas, and generators, must be in Odoo's `_SAFE_OPCODES`.

An installed Python package is not automatically usable. Imports are blocked;
only names explicitly injected by Odoo or included in its restricted built-ins
are visible to the Server Action.

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
- `b64encode`
- `b64decode`

Restricted functional built-ins confirmed in production include `map`,
`filter`, `reduce`, `sorted`, `zip`, `enumerate`, `sum`, `min`, `max`, `all`,
`any`, `set`, and `range`. `reduce` is injected directly; the `functools` and
`itertools` modules are not importable.

## Python 3.10 idioms under safe_eval

| Construct | Status | Guidance |
| --- | --- | --- |
| Small local helper without closure | supported | Prefer named pure helpers for repeated transformations. |
| Function parameter/return annotations using visible built-ins | production-confirmed | Use sparingly for helper contracts; no static checker runs in the UI. |
| Variable annotation | forbidden | Emits `SETUP_ANNOTATIONS`. |
| List/dict/set comprehension | production-confirmed | Keep it single-purpose and bounded. |
| Generator function/expression | production-confirmed | Useful with `sum`, `all`, or `any`; never hide ORM queries inside it. |
| `map` / `filter` / `reduce` | production-confirmed | Prefer a comprehension, `sum`, or an explicit loop when clearer. Always give `reduce` an initializer. |
| Ordered deduplication with `set` + `list` | production-confirmed | Use a set for O(1) membership and a list to preserve order. |
| Import-free decorator without closure | production-confirmed | Useful only for a real local contract; imported and closure-producing decorators remain unavailable. |
| Simple walrus expression | production-confirmed | Use only when it removes duplicate work without obscuring control flow. |
| Walrus inside a comprehension at module scope | forbidden | Can emit blacklisted `STORE_GLOBAL`. |
| Dict merge `left | right` | production-confirmed | Use for small copy-on-write dictionaries, not record mutation. |
| Self-documenting f-string | production-confirmed | Useful for diagnostics, but compact JSON remains the audit output contract. |
| `match` against scalar literals plus wildcard | production-confirmed | Use only when it is clearer than an `if/elif` chain. |
| Sequence, mapping, or class structural patterns | forbidden | Emit unsupported `MATCH_*`/`GET_LEN` opcodes. |
| Closure capturing an outer local | forbidden | Emits unsupported `LOAD_CLOSURE`/`LOAD_DEREF`; pass values explicitly instead. |
| Specific `try/except` | supported | Catch only errors the snippet can handle; never convert an unknown failure into `ok`. |
| `with` statement | forbidden in the audited allowlist | Do not build transaction/context-manager patterns inside snippets. |

Functional-first does not mean abstraction-first. Keep selection, ORM reads,
writes, logging, and action return in an explicit imperative shell; use pure
helpers or bounded comprehensions only for in-memory transformations. For ORM
data, prefer vectorized recordset methods, `search_count`, and `read_group` over
Python-level iteration.

Use literal `match` only for genuine scalar dispatch:

```python
match OUTPUT_MODE:
    case 'audit':
        output_kind = 'json'
    case 'open_records':
        output_kind = 'window_action'
    case _:
        raise UserError('unsupported_output_mode')
```

Do not rewrite a two-branch boolean check as `match`; that is modern-looking
ceremony, not an improvement.

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
- no structural `match` patterns, closures, or context-manager syntax

## Success and failure semantics

- Read-only audit can `raise UserError(payload_json)` because no writes should commit.
- Write success must set `action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {'type': 'success', 'title': '...', 'message': payload, 'sticky': True}}`.
- Write failure must `raise UserError(payload_json)` to abort and rollback.
