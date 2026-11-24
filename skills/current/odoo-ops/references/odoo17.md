# Odoo 17 specifics

Read this when the active profile has `odoo_version` 17 (`odoo-ops env --json`).

## Runtime

- The Odoo 17 runtime container runs Python 3.10. `datetime.UTC` (introduced in Python 3.11) is unavailable; use `timezone.utc` from `datetime` instead.
- Odoo 17 bundles QUnit 2.9.1. Modern assertion helpers like `assert.true()` and `assert.false()` do not exist; use `assert.ok()` or strict equality checks.

## APIs from later versions

Docs and examples for Odoo 18 to 20 use APIs that 17.0 lacks. Use the 17 equivalent:

| Later API | Odoo 17 equivalent |
| --- | --- |
| Field `aggregator=` | `group_operator=` |
| `check_access(op)` | `check_access_rights(op)` then `check_access_rule(op)` |
| `has_access(op)`, `_filtered_access(op)` | `check_access_rights(op, raise_exception=False)`, `_filter_access_rules(op)` |
| `models.Constraint`, `models.Index` | `_sql_constraints`, field `index=` |
| `Domain` class | `odoo.osv.expression` (`AND`, `OR`, `normalize_domain`) |
| `self.env._("...")` | `from odoo import _` |
| `env.user.has_groups(...)`, `res.groups.privilege_id` | `user_has_groups(...)` or `env.user.has_group(xmlid)`, `category_id` |
| Route `type="json2"`, bearer API keys | Route `type="json"` (JSON-RPC) |
| `<list>` view tag, `<chatter/>` | `<tree>`, `<div class="oe_chatter">` |
| `Interaction` public classes | `publicWidget` (OWL is 2.8.x on 17 and 19; OWL 3 `computed` exists on neither) |
| Cron `_commit_progress` | Process a batch, commit, then `self.env.ref(cron_xmlid)._trigger()` for the rest |

The route option `readonly=` is accepted in 17 but nothing reads it (`odoo/http.py`), so it has no effect.

These look newer but exist in 17.0: `@api.private`, `fields.NO_ACCESS`, `_allow_sudo_commands`, `odoo.tools.SQL`, `search_fetch`, `_read_group(domain, groupby, aggregates)`, `_compute_display_name`, `precompute=`, and `_check_company_domain`. Some arrived by backport: `@api.private` reached 17.0 in February 2025, so an older 17.0 build lacks it. Check the provisioned source with `rg -n "def private" <runtime_path>/odoo/api.py` before relying on one.

## Idiomatic Odoo 17 code

| Need | Odoo 17 idiom |
| --- | --- |
| Unique or check constraint | `_sql_constraints = [("code_uniq", "UNIQUE(code)", "msg")]`; physical name `<table>_<name>` |
| Display name | `_compute_display_name` with `@api.depends`; `name_get` is deprecated in 17 |
| Name search | `_rec_names_search`, or override `_name_search(name, domain, operator, limit, order)` |
| Access checks | `check_access_rights(op)` then `check_access_rule(op)`; `_filter_access_rules(op)` to filter |
| Domain building | `odoo.osv.expression` (`AND`, `OR`, `normalize_domain`) |
| Translations | `from odoo import _`; `_lt` for module-level lazy strings |
| Group checks | `self.env.user.has_group(xmlid)`; `user_has_groups(spec)` on any model |
| Views | `<tree>` root, `<div class="oe_chatter">` in forms, kanban `t-name="kanban-box"` |
| Mark an activity done | `action_feedback(feedback=...)`; activity types with `keep_done` keep done activities archived |
| Discuss payloads | `_channel_info()` and `_message_format()` |
| JS tests | QUnit (see Runtime) |
