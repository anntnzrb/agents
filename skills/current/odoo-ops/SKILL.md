---
disable-model-invocation: true
name: odoo-ops
description: "Odoo 17 local replica development, database inspection, Server Actions, and explicitly authorized JSON-RPC."
license: AGPL-3.0-or-later
---

# Odoo Ops

## Before you act

Follow these situational reading rules before taking action:
- Before any production RPC, you MUST read [references/safety-model.md](references/safety-model.md).
- Before local DB or shell work, you MUST read [references/db-recipes.md](references/db-recipes.md).
- Before SQL on Odoo tables, crons, QUnit, or debugging, you MUST read [references/gotchas.md](references/gotchas.md).
- Before auditing slow views, chat saturation, or pre-deploy field removals, you MUST read [references/perf-diagnostics.md](references/perf-diagnostics.md).
- Before inspecting routes, you MUST read [references/route-safety.md](references/route-safety.md).
- Before auditing or fixing XML views, you MUST read [references/xml-view-rules.md](references/xml-view-rules.md).
- Before interpreting CLI inspection JSON, you MUST read [references/output-contracts.md](references/output-contracts.md).
- Before writing Server Action templates for user UI execution, you MUST read [references/server-action-capabilities.md](references/server-action-capabilities.md), [references/server-action-playbook.md](references/server-action-playbook.md), [references/server-action-safe-eval.md](references/server-action-safe-eval.md), [references/server-action-sql-safety.md](references/server-action-sql-safety.md), and [references/server-action-templates.md](references/server-action-templates.md).
- Before analyzing CLI JSON outputs in an OMP Eval kernel, you MUST read [references/omp-eval.md](references/omp-eval.md).

## Safety boundary

- The skill CLI is the single interface between user, model, and Odoo. Execute all commands via `uv run --script <skill-dir>/scripts/cli.py` in shell. Agents MUST NOT write custom HTTP, XML-RPC, or JSON-RPC scripts, import skill transports or Python modules into notebooks or eval kernels, or use `curl`/`requests`/`urllib`. Stop and report any missing CLI capability.
- Explore first: inspect provisioned source (`env --json`: `runtime_path`, `addons_paths`) and extend native primitives before designing changes or interventions. Never invent modules or APIs.
- Local replica (`<prodDB>_work_YYYYMMDD`): unrestricted reads and writes for fast iteration. Seed replica (`<prodDB>_seed_<YYYYMMDD>`) is an untouched baseline; never write to it. Rebuild broken replicas with `db-clone`.
- Production reads: no per-read approval required. Credentials auto-load from `<skill-dir>/.env` (`--env-file` overrides). Pass `--allow-rpc` on every RPC invocation (before or after the subcommand). Placing RPC flags before `rpc` exits 2 with a hint.
- Production writes: plan and apply workflow. Any mutation without `--write` creates a dry-run plan (on loopback too). On production, passing `--write` on direct mutations is blocked; `--write` is valid exclusively with `apply <plan-id>`.
  1. Rehearse logic on local replica (validate behavior, not IDs).
  2. Run mutation command without `--write` to generate a dry-run plan and plan ID.
  3. Present plan ID and diff to user and request approval.
  4. Only after explicit approval, run `rpc --allow-rpc --write apply <plan-id>`.
  5. Postcheck with reads. Approval is consumed immediately; subsequent batches require a fresh plan and approval.
  6. Revert: `rpc --allow-rpc revert <plan-id>` creates a restore plan from the backup.
  7. Plans and backups live in the state dir automatically (`ODOO_OPS_STATE_DIR` or XDG state `odoo-ops`).
- Hard deny-list on production (CLI refuses; instruct user to use Odoo web UI): `unlink`/`delete`, module install/upgrade/uninstall, schema/field/ACL/rule changes, server action `run`, cron `method_direct_trigger`, sending email/WhatsApp/SMS, `message_post`, partner merge, accounting post/reconcile, budget sign/liquidate, payslip done, `set_param`, password changes. Server Action templates provide the user's manual UI path; keep `WRITE_APPROVED = False` by default.
- Data discipline: no PII masking (exact values required); request only necessary fields (`--fields`). NEVER print tokens or read secrets from `ir_config_parameter` into output. NEVER upload data to public hosts.
- Long SQL or ORM scripts: write to `<temp-dir>` and pass `--file`.

## Public entrypoint

```text
uv run --script <skill-dir>/scripts/cli.py <command> ...
```

In examples below, `odoo-ops` represents this exact command.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Permission and production boundaries | [Safety model](references/safety-model.md) | Before RPC or production work |
| Local paths and database identity | [Runtime discovery](references/runtime-discovery.md) | Before local runtime or database operations |
| Local SQL, ORM shell, and cloning | [Database recipes](references/db-recipes.md) | Querying or rebuilding a replica |
| Technical facts and environment quirks | [Gotchas](references/gotchas.md) | Writing SQL, crons, tests, or debugging |
| Performance and pre-deploy auditing | [Performance diagnostics](references/perf-diagnostics.md) | Auditing slow views, notifications, or field removals |
| Static controller inspection | [Route safety](references/route-safety.md) | Listing or assessing routes |
| XML view rules and AST linting | [XML view rules](references/xml-view-rules.md) | Auditing or fixing XML views and QWeb templates |
| Command results | [Output contracts](references/output-contracts.md) | Interpreting inspection output |
| Action selection | [Server Action capabilities](references/server-action-capabilities.md) | Choosing UI actions, automation, or addons |
| Production action workflow | [Server Action playbook](references/server-action-playbook.md) | Preparing or executing production actions in the UI |
| Sandbox restrictions | [safe_eval reference](references/server-action-safe-eval.md) | Writing Server Action Python |
| Direct SQL writes | [SQL safety](references/server-action-sql-safety.md) | Preparing set-based Server Actions for the UI |
| Template contracts | [Template catalog](references/server-action-templates.md) | Rendering any bundled template |
| Local analysis of CLI output files | [OMP Eval companion](references/omp-eval.md) | Analyzing saved CLI JSON datasets in Eval |

## Common calls

```text
odoo-ops env --json
odoo-ops dev <workflow>
odoo-ops health --wait 30
odoo-ops test <module> --tags /<module>:Class.test_method
odoo-ops test <module> --parallel -j 4
odoo-ops test <module> --tags /<module>:Class.test_method --baseline <ref>
odoo-ops auth-temp --db <prodDB>_work_<YYYYMMDD>
odoo-ops auth-restore --db <prodDB>_work_<YYYYMMDD>
odoo-ops lint <module>
odoo-ops fmt <module> --check
odoo-ops lint-views <module>
odoo-ops stop --web
odoo-ops logs -c web -f
odoo-ops prune
odoo-ops db-list
odoo-ops db-drop <prodDB>_work_<YYYYMMDD> --force
odoo-ops db-restore <dump>.sql.gz <prodDB>_seed_<YYYYMMDD> --force
odoo-ops db-clone <prodDB>_seed_<YYYYMMDD> <prodDB>_work_<YYYYMMDD> --force
odoo-ops db-query --file <temp-dir>/query.sql --db <prodDB>_work_<YYYYMMDD>
odoo-ops shell --file <temp-dir>/script.py --db <prodDB>_work_<YYYYMMDD>
odoo-ops routes --json
```

## Authorized JSON-RPC

Credentials load automatically from `<skill-dir>/.env`. Every call requires `--allow-rpc`. `--fields` accepts space-separated, comma-separated, or JSON array strings. `search_read` defaults to `--limit 10` and warns on truncation.

Read operations:
```text
odoo-ops rpc --allow-rpc search_read crm.lead '[["user_id", "=", 2]]' --fields 'name stage_id' --limit 20
odoo-ops rpc --allow-rpc count crm.lead '[["active", "=", true]]'
odoo-ops rpc --allow-rpc read crm.lead '[101, 102]' --fields 'name probability'
odoo-ops rpc --allow-rpc read_group crm.lead '[["active", "=", true]]' --groupby stage_id
odoo-ops rpc --allow-rpc fields_get crm.lead --fields 'name stage_id'
odoo-ops rpc --allow-rpc get_view crm.lead --view-type form
odoo-ops rpc --allow-rpc metadata crm.lead '[101]'
odoo-ops rpc --allow-rpc external_id crm.lead '[101]'
odoo-ops rpc --allow-rpc default_get crm.lead name user_id
odoo-ops rpc --allow-rpc check_access crm.lead read
odoo-ops rpc --allow-rpc user_has_groups base.group_user
odoo-ops rpc --allow-rpc call crm.lead <read_method> --ids '[101]' --args '[]' --kwargs '{}'
```

Production mutation workflow:
```text
# 1. Generate dry-run plan (no --write)
odoo-ops rpc --allow-rpc write crm.lead '[101]' '{"priority": "2"}'
odoo-ops rpc --allow-rpc write-batch crm.lead <temp-dir>/batch.json
odoo-ops rpc --allow-rpc archive crm.lead '[101]'

# 2. Apply plan after explicit user approval
odoo-ops rpc --allow-rpc --write apply <plan-id>

# 3. Create revert plan if rollback needed
odoo-ops rpc --allow-rpc revert <plan-id>
```

## Flags that trip agents

- `test`: use `--tags /<module>:Class.test_method`. NEVER use `-k` or `--`. Tests run in an `odoo-test-*` container but update modules (`-u`) on the same database as `dev`; a running `dev` server can drop sessions or reload. Run `health --wait 60` before browser checks after a test run. An internal lock (`odoo-ops.lock`) serializes test runs and pod creation. Prints `RESULT tests= failed= errors=`.
- `test --baseline <ref>`: separates new failures from pre-existing ones by running the same tests on `<ref>` in a temporary git worktree. Use it instead of `git stash`. Exit 0 means no new failures.
- `auth-temp` / `auth-restore`: local login for UI verification. `auth-temp` backs up the user's hash and sets a random password; ALWAYS run `auth-restore` when done, even if verification fails. Never set passwords with SQL.
- `shell`: requires `dev` running (local pod and DB must be up). Refuses `_seed_` and production. Commits on exit unless `--rollback` is passed.
- `search_read`: defaults to `--limit 10` and warns on truncation. Pass `--limit` explicitly when needed.
- `read`: has no `--limit` flag. Use `search_read` when pagination or limiting is needed.
- `check_access`: takes positional action `{read,write,create,unlink}`, not `--operation`.
- `default_get`: takes space-separated positional field names, not a JSON array.
- `read_group`: domain is positional before flags (`read_group <model> [domain] --groupby f [f ...]`). Flags like `--groupby` consume arguments that follow them.
- `call`: takes positional `model` and `method` plus `--ids JSON`, `--args JSON`, `--kwargs JSON`.
- `write-batch`: takes positional `model` and `file` mapping record ID to values dict.
- RPC flag placement: `--allow-rpc` can appear before or after the subcommand. Placing RPC flags before `rpc` exits 2 with a hint.
- On production: passing `--write` on direct mutations is blocked; `--write` is valid exclusively with `apply <plan-id>`.
- Container logs: use `logs -c web|db|test`. Container names are `odoo-db` and `odoo-web`.
- Use `127.0.0.1` rather than `localhost` to avoid IPv6 binding failures.
- Do not run `git stash` while `dev` is running; filesystem changes trigger autoreload crashes.
