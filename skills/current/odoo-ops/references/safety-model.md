# Safety Model

The `odoo-ops` skill is the single interface between user, model, and Odoo. All interactions MUST proceed through `uv run --script <skill-dir>/scripts/cli.py` via shell. Agents MUST NOT write their own HTTP, XML-RPC, or JSON-RPC clients, import transport libraries, use `urllib`, `requests`, or `curl` against Odoo endpoints, or rely on harness-specific execution kernels (such as notebook or eval tools). If the CLI lacks a required operation, stop and report the capability gap.

Explore first: before designing code modifications, planning production interventions, or explaining system mechanics, inspect the provisioned Odoo source tree (resolved via `env --json`: `runtime_path` and `addons_paths`) and extend native primitives. Never invent arbitrary modules or non-existent APIs. Prefer native business mechanisms (such as `activity_schedule` paired with `action_feedback`) over custom state tracking.

## Local Replica: Free Iteration

The disposable local replica (`<prodDB>_work_YYYYMMDD`) is the default workspace. It provides unrestricted reads and writes for rapid development, testing, schema experimentation, and repair workflows:

- Work replicas allow arbitrary ORM operations, SQL queries, and module upgrades without prompt gates.
- If a work replica breaks or contains corrupt test data, drop it and recreate a clean copy from the seed using `db-clone`.
- The seed database (`<prodDB>_seed_<YYYYMMDD>`) is an untouchable baseline restored directly from the DBA dump. Never install modules, run migrations, or execute writes against the seed.
- The `shell` command runs interactive or script-based ORM Python on the local replica. By default, changes commit upon clean exit; use `--rollback` to test scripts safely. The CLI refuses to run `shell` against seed databases or production endpoints.
- When executing long SQL statements or complex Python scripts, write them to a temporary file (`<temp-dir>`) and invoke `db-query --file PATH` or `shell --file PATH`. You do not need to delete temporary files after execution.
- Pod creation and test execution are serialized by an internal lock in the CLI. Parallel agents do not need external wrapper locks like `flock`.

## Production: Read-Only by Default

Production is read-only by default. Read operations do not require per-query user approval. Connection credentials load automatically from `<skill-dir>/.env` (maintained by configuration sync). The `--env-file` parameter is reserved for manual overrides.

Every `rpc` invocation requires the mechanical `--allow-rpc` flag. The flag may be placed before or after the operation subcommand (e.g. `rpc --allow-rpc search_read ...` or `rpc search_read ... --allow-rpc`). Placing RPC flags before the `rpc` command itself produces a hint and exits 2. The flag acknowledges remote execution; it prevents unintended execution when commands are pasted into non-RPC contexts.

### Data Privacy and Secret Handling
- No PII masking: the user owns production data and requires exact, unmangled values for operational correctness.
- Request discipline: query only the specific fields needed (`--fields`). `search_read` defaults to `--limit 10` and warns on truncation. Never dump full tables or broad `search_read` sets into the conversation context.
- Secret protection: NEVER print connection tokens, passwords, or `.env` values into stdout or chat. NEVER read secrets or credentials from `ir_config_parameter` into user-visible output.
- Data confinement: NEVER upload replica or production data, dumps, or query exports to public file hosts, external pastebins, or third-party web services.

## Production Writes: Plan and Apply Workflow

Production write operations are strictly gated. Any mutation requires explicit user authorization for that specific batch. On production endpoints, passing `--write` on direct mutation commands is blocked; `--write` is valid exclusively with `apply <plan-id>`.

Any mutation command executed without `--write` creates a dry-run plan (both on production and loopback). Every production mutation follows a mandatory lifecycle:

1. **Rehearsal (Recommended):** Rehearse the operation on the local working replica to validate business logic and constraint handling. Because local replica data differs from production, validate logic and behavior, not concrete record IDs.
2. **Dry-Run Plan:** Execute the mutation command WITHOUT the `--write` flag. The CLI generates a dry-run plan containing a pre-image snapshot, an old-to-new field diff, affected record counts, and a unique plan ID:
   ```text
   uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc write crm.lead '[101, 102]' '{"priority": "2"}'
   ```
3. **User Review:** Present the generated plan ID and summarized diff to the user, explicitly requesting authorization to apply the change.
4. **Guarded Application:** ONLY after explicit approval for that specific plan, run:
   ```text
   uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc --write apply <plan-id>
   ```
   The `apply` command verifies record state against the plan pre-image. If any target record has changed since the plan was created, `apply` aborts immediately to prevent overwriting concurrent updates. Upon successful application, it automatically stores a rollback backup.
5. **Postcheck:** Verify the updated state immediately using read-only queries (`read` or `search_read`).
6. **Authorization Consumed:** Applying the plan consumes the authorization. The environment returns to read-only status immediately. Any subsequent mutation batch requires a fresh dry-run plan and distinct approval.

### Plan and Backup Storage
Plans and backups are automatically managed within the skill state directory (`ODOO_OPS_STATE_DIR` or XDG state directory `odoo-ops`). The user and agent never supply filesystem paths for plan storage.

### Reverting Applied Changes
If an applied plan must be rolled back, execute:
```text
uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc revert <plan-id>
```
This generates a restore plan from the pre-image backup. The restore plan itself requires explicit user approval before execution with `apply <restore-plan-id>`.

### Common Sense Constraints
Even when authorized by the user:
- NEVER invent or fabricate identification numbers (e.g. tax IDs, citizen IDs, passport numbers).
- NEVER execute mutations beyond the boundaries of the approved plan.

## Hard Deny-List on Production

The CLI strictly refuses the following operations on production endpoints. If asked to perform them, inform the user that policy requires executing them directly through the Odoo web interface:

1. `unlink` / `delete`: record deletion is prohibited on production.
2. Module operations: `install`, `upgrade`, or `uninstall` of Odoo modules.
3. Schema and metadata: altering models, fields, access control lists (`ir.model.access`), record rules (`ir.rule`), security groups, or `ir.config_parameter`.
4. Immediate background actions: invoking `run` on `ir.actions.server` or `method_direct_trigger` on `ir.cron`. Creating and executing Server Actions in production is done by the user in the Odoo web UI.
5. Outbound communications: sending email, WhatsApp messages, SMS, creating messages (`message_post` / notifications), or launching mass mailings.
6. Partner reconciliation: `res.partner` automated or manual merging.
7. Accounting and payroll: posting journal entries, reconciling bank statements, signing or liquidating budgets, and setting payslips to `done`.
8. System credentials: modifying `set_param` values or changing user passwords.

Server Action templates remain valid as the user's manual UI path. Keep their `WRITE_APPROVED = False` safety by default, setting it to `True` only after explicit user review.

**Allowed Production Mutations:**
Record archival (`archive`), unarchival (`unarchive`), field updates (`write`), batch updates (`write-batch`), record duplication (`copy`), and invocations of public business methods not on the deny-list are permitted exclusively through the two-phase dry-run plan and apply workflow.

**Reason:** JSON-RPC commits each call independently. Server transactions cannot be rolled back after the HTTP response completes. Denied operations carry irreversible side effects or external communication risks that cannot be undone by restoring data backups.

## Read-Only Caveats

Client-side read allowlists inspect method names (`search_read`, `count`, `read`, `read_group`, `fields_get`, `get_view`, `metadata`, `external_id`, `default_get`, `check_access`, `user_has_groups`), but cannot enforce database transaction read-only isolation on the server. Computed fields with poorly designed `compute` methods or custom overrides can trigger database updates.

In addition, `export_data` is excluded from the read allowlist: [`odoo/models.py`](https://github.com/odoo/odoo/blob/17.0/odoo/models.py) routes `export_data` through `_export_rows` and `__ensure_xml_id`, which inserts rows into `ir_model_data` for records lacking external IDs. Always use `read` or `search_read` with explicit field lists for inspection.
