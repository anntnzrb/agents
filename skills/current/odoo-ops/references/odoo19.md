# Odoo 19 specifics

Read this when the active profile has `odoo_version` 19 (`odoo-ops env --json`). Paths are relative to the provisioned `odoo` package (`runtime_path/source/odoo-19.0*/odoo`). Verified on build `19.0+e.20261120`; check the provisioned source before relying on a fact for another build.

## Runtime

- Python 3.10 to 3.14 and PostgreSQL 13 or later (`release.py`, `MIN_PY_VERSION`, `MAX_PY_VERSION`, `MIN_PG_VERSION`).
- The ORM lives in `orm/` (`orm/models.py`, `orm/fields*.py`, `orm/domains.py`), not in `models.py`/`fields.py`.
- OWL is 2.8.x (`addons/web/static/lib/owl/owl.js`), as on 17; OWL 3 APIs do not exist.

## Source path map

References that cite the 17 layout map to 19 as follows:

| Odoo 17 | Odoo 19 |
| --- | --- |
| `odoo/models.py` | `odoo/orm/models.py` |
| `odoo/fields.py` | `odoo/orm/fields.py` plus `fields_textual.py`, `fields_relational.py`, and the other `orm/fields_*.py` |
| `odoo/fields.py`, `Command` | `odoo/orm/commands.py` |
| `odoo/fields.py`, `NO_ACCESS` | `odoo/orm/models.py` |
| `odoo/api.py` (decorators, `Environment`) | `odoo/orm/decorators.py`, `odoo/orm/environments.py` (imported as `odoo.api`) |
| `odoo/osv/expression.py` | `odoo/orm/domains.py` (`Domain`, imported from `odoo.fields`) |
| `odoo/modules/graph.py` | Removed; module loading is in `odoo/modules/loading.py` |

## Removed or renamed: code that fails

| Odoo 17 code | Odoo 19 replacement | Evidence |
| --- | --- | --- |
| `<tree>` view, `view_mode="tree"`, `//tree` locators | `<list>`, `list`, `//list` (`lint-views` rule `ODOO_XML_010`) | `addons/base/models/ir_ui_view.py`, `type` selection |
| `_sql_constraints = [...]` | `_name_uniq = models.Constraint("UNIQUE(name)", "msg")`, `models.Index(...)`; the old list is ignored with a warning, so uniqueness silently disappears | `orm/model_classes.py`, "no longer supported" |
| `name_get()` | `_compute_display_name()`; read `display_name` | No `name_get` in `orm/models.py` |
| `_name_search(name, domain, operator, limit, order)` | `_search_display_name(operator, value)` | `orm/models.py`, `_search_display_name` |
| `name_search(name, args, ...)` | Parameter renamed `domain` | `orm/models.py`, `name_search` |
| `_search(domain, offset, limit, order, access_rights_uid)` | `_search(domain, offset, limit, order, *, active_test=True, bypass_access=False)`; core passes the keywords, so an override without them raises `TypeError` | `orm/models.py`, `orm/fields_relational.py`, `orm/domains.py` |
| `user_has_groups(...)` | `self.env.user.has_group(xmlid)` | Absent from `orm/models.py` |
| `groups_id` on `res.users`, `ir.ui.menu`, `ir.actions.act_window`, `ir.actions.server` | `group_ids` | `addons/base/models/res_users.py`, `ir_ui_menu.py`, `ir_actions.py` |
| `res.groups.category_id` | `privilege_id` (`res.groups.privilege`, which holds `category_id`) | `addons/base/models/res_groups.py`, `res_groups_privilege.py` |
| `res.partner.mobile`, `crm.lead.mobile`, `mobile_blacklisted` | `phone` | Absent from the 19 models |
| `crm.stage.team_id` | `team_ids` (Many2many) | `addons/crm/models/crm_stage.py` |
| `mail.activity.type.keep_done` | None: done activities are always archived | `addons/mail/models/mail_activity.py`, `_action_done` |
| `discuss.channel._channel_info()`, `channel_fold()`; member `fold_state`, `is_minimized` | `_to_store_defaults(target)`, `_to_store(store, fields)` (Store API) | `addons/mail/models/discuss/discuss_channel.py` |
| `purchase.order.action_create_invoice(self)` | `action_create_invoice(self, attachment_ids=False)` | `addons/purchase/models/purchase_order.py` |
| `@web/webclient/actions/action_hook` (`useSetupAction`) | `@web/search/action_hook` | `addons/web/static/src/search/action_hook.js` |
| `@mail/core/common/thread_service`, `@mail/discuss/core/web/channel_selector` | No equivalent module; `DiscussSidebarCategories` moved to `@mail/discuss/core/public_web/discuss_sidebar_categories` | `addons/mail/static/src/` |

Enterprise model changes: `account_budget` replaces `crossovered.budget`, `crossovered.budget.lines` and `account.budget.post` with `budget.analytic` and `budget.line`; `hr.contract` and the `hr.payslip.employees` wizard are gone (`hr.version`, `hr.payslip.run.generate_payslips`); `sign.request._generate_completed_document(password)` became `_generate_completed_documents()`.

## Deprecated: still works, emits `DeprecationWarning`

| Odoo 17 code | Odoo 19 code | Evidence |
| --- | --- | --- |
| `read_group(...)` | `_read_group(...)`, or `formatted_read_group(...)` for the formatted result | `orm/models.py`, `read_group` |
| `check_access_rights(op)`, `check_access_rule(op)` | `check_access(op)`, `has_access(op)` | `orm/models.py` |
| `_filter_access_rules(op)` | `_filtered_access(op)` | `orm/models.py` |
| `_check_recursion()` | `_has_cycle()` | `orm/models.py` |
| `toggle_active()` | `action_archive()`, `action_unarchive()` | `orm/models.py` |
| `self._cr`, `self._context`, `self._uid` | `self.env.cr`, `self.env.context`, `self.env.uid` | `orm/models.py` |
| Field `group_operator=` | `aggregator=` | `orm/fields.py` |
| `odoo.osv.expression` | `odoo.fields.Domain` | `osv/expression.py` |
| `@route(type="json")` | `@route(type="jsonrpc")` | `http.py` |

Warnings are hidden by default; run with `PYTHONWARNINGS=default` to see them.

## Idiomatic Odoo 19 code

Patterns the 19 core addons use; follow them in new code.

| Need | Odoo 19 idiom | Evidence |
| --- | --- | --- |
| Unique or check constraint | `_code_uniq = models.Constraint("UNIQUE(code)", "msg")`; physical name `<table>_<attribute without leading _>`. `models.Index`, `models.UniqueIndex` for indexes | `orm/table_objects.py`, `full_name` |
| Domain building | `from odoo.fields import Domain`; `Domain("state", "=", "done") & Domain(...)`, `Domain.AND([...])` | `addons/sale/models/*.py` imports |
| Translations | `self.env._("text %s", value)`; `_lt` for module-level lazy strings | `orm/environments.py`, `_` |
| Group checks | `self.env.user.has_group("base.group_user")`; `has_groups("base.group_user,!base.group_portal")` for a spec | `addons/base/models/res_users.py`, `has_groups` |
| Access checks | `check_access(op)` raises; `has_access(op)` returns a boolean; `_filtered_access(op)` filters records | `orm/models.py` |
| Grouped reads | `_read_group(domain, groupby, aggregates)` in server code; `formatted_read_group` for the web-client format | `orm/models.py`; `addons/web/models/models.py` |
| Cron batches | Process a batch, then `self.env["ir.cron"]._commit_progress(processed, remaining=...)` | `addons/base/models/ir_cron.py`, `_commit_progress` |
| Company-dependent fields | Stored as a `jsonb` column on the model (no `ir.property` rows); indexed `btree_not_null` by default | `orm/fields.py`, `column_type` |
| JSON routes | `type="jsonrpc"` for the web client; `type="json2"` for the bearer-key external API; `readonly=` is honoured | `http.py` |
| Views | `<list>` root, `<chatter/>` in forms, kanban card template `t-name="card"` (no `kanban-box`) | 19 core views |
| Mark an activity done | `action_feedback(feedback=...)` posts the message and archives the activity | `addons/mail/models/mail_activity.py` |
| Discuss payloads | `_to_store_defaults(target)` / `_to_store(store, fields)` with `Store` | `addons/mail/tools/discuss.py` |
| Public website JS | `Interaction` classes (`@web/public/interaction`); `publicWidget` is legacy | `addons/web/static/src/public/interaction.js` |
| JS tests | Hoot (`@odoo/hoot`) | `addons/web/static/lib/hoot` |

## Migrating 17 code

- Fix "Removed or renamed" before "Deprecated": the first set stops a module from installing or crashes at runtime.
- An override of a method that no longer exists raises no error; its logic simply stops running. After porting, check that every override still has a parent method in the 19 source.
- Do not reintroduce `_sql_constraints`; give a `models.Constraint` the same name as the old tuple entry so the physical constraint name stays the same.
