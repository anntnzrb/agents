# Module Security

Access-control facts and review checks for custom Odoo 17 module code. Paths are relative to the provisioned Odoo source (`env --json`: `runtime_path`).

## RPC entry points

- Every public model method is callable over RPC by any user who can reach the model. `odoo/service/model.py` (`get_public_method`) refuses only names starting with `_`, methods decorated with `@api.private`, and unsafe attributes.
- Name helper methods with a leading `_`. Use `@api.private` (`odoo/api.py`) only for an existing public method that must stop being RPC-callable.
- A public method that writes, calls `sudo()`, or returns data MUST check the caller first: `self.check_access_rights(op)` for model ACLs (`ir.model.access`), then `self.check_access_rule(op)` for record rules. Odoo 17 has no combined `check_access` model method; the CLI's `check_access` subcommand wraps `check_access_rights`.
- Button methods (`type="object"`) are public methods. Hiding a button in the view does not stop an RPC call.

## sudo() boundaries

- `sudo()` skips model ACLs (`ir.model.access.check` returns early when `env.su`) and record rules (`check_access_rule`, `_filter_access_rules`).
- `sudo()` does not skip `_check_company`: with `_check_company_auto = True`, `create` and `write` still reject cross-company links.
- Elevate the narrowest recordset for the shortest span. Validate inputs and the caller's access before `sudo()`, never after.
- Never pass caller-supplied domains, field names, or values into a sudo call without a whitelist.
- x2many `Command` values in a sudo `write` or `create` also run as superuser on the comodel. A comodel that sets `_allow_sudo_commands = False` runs them as the original user instead (`odoo/fields.py`, `_check_sudo_commands`). Whitelist command lists from request input like other values.
- Never return sudo-read data to a caller who could not read it directly.

## Related and computed fields

- Related fields compute as superuser by default: `compute_sudo` defaults to `related_sudo`, which defaults to `True` (`odoo/fields.py`, `Field._get_attrs`). A related field exposes the target value to every user who can read the source record, even without access to the target model.
- Stored computed fields also default to `compute_sudo=True`; non-stored computed fields default to `False`.
- When a related field exposes sensitive data, restrict it with `groups=` or set `related_sudo=False`, then test as a user without access to the target model.
- `groups=fields.NO_ACCESS` hides a field from every ORM caller except sudo code (`odoo/fields.py`, `NO_ACCESS`).

## Raw SQL and QWeb output

- Build raw SQL with `odoo.tools.SQL`: pass values as `%s` arguments and table or column names through `SQL.identifier(name)`. Never format request values into a query string.
- Raw SQL skips ACLs, record rules, and the `active` filter. Prefer the ORM when the caller's access matters.
- Render QWeb output with `t-out`, which escapes unless the value is `Markup`. `t-esc` and `t-raw` are deprecated in 17; `t-raw` does not escape and logs a deprecation warning (`odoo/addons/base/models/ir_qweb.py`).
- Wrap a value in `markupsafe.Markup` only after you build or sanitize that HTML yourself.

## Record rules and multi-company

- Rule composition (`odoo/addons/base/models/ir_rule.py`, `_compute_domain`): global rules (no groups) combine with AND. Rules for the user's groups combine with OR, and that union combines with AND against the global rules. A group rule cannot widen access past a global rule.
- Multi-company isolation is a global rule on `company_id`, usually `['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]`. A new model with `company_id` needs its own rule; nothing adds one automatically.
- Set `_check_company_auto = True` on the model and `check_company=True` on relational fields that must stay within one company. `_check_company` (`odoo/models.py`) checks only those fields, on `create` and `write`.
- Test a security change as a non-admin user. Cover a user without the group and a user in another company; assert `AccessError` or `UserError` with `assertRaises`.

## Review checklist

1. List every new or changed public method and button; confirm each one checks access or is private.
2. Find every `sudo()`; confirm the elevated scope is minimal and its inputs are validated.
3. Find every new related field; confirm the target data is safe for every reader of the source model.
4. For a new model: confirm the ACL lines in `ir.model.access.csv` and, when it has `company_id`, a multi-company rule plus `check_company` on its relational fields.
5. Search the provisioned addons paths for overrides and callers of changed methods before narrowing their access.
