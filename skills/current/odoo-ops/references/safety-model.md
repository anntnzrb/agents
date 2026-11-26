# Safety Model

The `odoo-ops` skill is the single interface between user, model, and Odoo. All interactions MUST proceed through `uv run --script <skill-dir>/scripts/cli.py` via shell. Agents MUST NOT write their own HTTP, XML-RPC, or JSON-RPC clients, import transport libraries, use `urllib`, `requests`, or `curl` against Odoo endpoints, or rely on harness-specific execution kernels (such as notebook or eval tools). If the CLI lacks a required operation, stop and report the capability gap.

Explore first: before designing code modifications, planning production interventions, or explaining system mechanics, inspect the provisioned Odoo source tree (resolved via `env --json`: `runtime_path` and `addons_paths`) and extend native primitives. Never invent arbitrary modules or non-existent APIs. Prefer native business mechanisms (such as `activity_schedule` paired with `action_feedback`) over custom state tracking.

## Local Replica: Free Iteration

The disposable local replica (`<prodDB>_work_<YYYYMMDD>`) is the default workspace. Use it for development, testing, schema experiments, and repairs:

- Work replicas allow ORM operations and module upgrades. SQL writes require `db-query --unsafe`.
- If a work replica breaks or contains corrupt test data, drop it and recreate a clean copy from the seed using `db-clone`.
- The seed database (`<prodDB>_seed_<YYYYMMDD>`) is a baseline restored from the DBA dump or created by cloning a clean installation. Keep it untouched between planned replacements with `db-restore` or `db-clone`.
- The `shell` command runs interactive or script-based ORM Python on the local replica. By default, changes commit upon clean exit; use `--rollback` to test scripts safely. The CLI refuses to run `shell` against seed databases or production endpoints.
- When executing long SQL statements or complex Python scripts, write them to a temporary file (`<temp-dir>`) and invoke `db-query --file PATH` or `shell --file PATH`. You do not need to delete temporary files after execution.
- The CLI serializes pod creation and test runs with internal locks; external `flock` wrappers are unnecessary. See [Runtime discovery](runtime-discovery.md#isolation-and-multi-agent-concurrency).

## Production: Read-Only by Default

Production is read-only by default. Read operations do not require per-query user approval. Start with `rpc --allow-rpc <operation> ...` without `--profile`, even if the checkout is on a migration branch. RPC flags and exported `ODOO_RPC_*` values take precedence over file settings. The CLI reads `<skill-dir>/.env` if present. `--env-file` or `ODOO_ENV_FILE` selects another file.

Every `rpc` invocation requires the mechanical `--allow-rpc` flag. The flag may be placed before or after the operation subcommand (e.g. `rpc --allow-rpc search_read ...` or `rpc search_read ... --allow-rpc`). Placing RPC flags before the `rpc` command itself produces a hint and exits 2. The flag acknowledges remote execution; it prevents unintended execution when commands are pasted into non-RPC contexts.

### Data Privacy and Secret Handling
- Operational accuracy: preserve exact values in private import files, mutation plans, and comparisons. Do not replace an actual identifier with a masked value in a write payload.
- Evidence and handoffs: mask PII in chat. Use synthetic identities and consistent fictitious relation IDs in offline fixtures. Inspect free-text descriptions and notes as well as structured fields. For sanitized exports, the procedure lives in [Import and audit workflow](import-and-audit-workflow.md).
- Request discipline: query only the specific fields needed (`--fields`). `search_read` defaults to `--limit 10` and warns on truncation. Never dump full tables or broad `search_read` sets into the conversation context.
- Secret protection: NEVER print connection tokens, passwords, or `.env` values into stdout or chat. NEVER read secrets or credentials from `ir_config_parameter` into user-visible output.
- Data confinement: NEVER upload replica or production data, dumps, or query exports to public file hosts, external pastebins, or third-party web services.

## Production Writes: Plan and Apply Workflow

Any production mutation requires explicit user approval for that batch. Pass `--write` with `apply <plan-id>`. Direct mutation commands reject `--write` on production and execute with it on loopback.

Any allowed mutation command executed without `--write` creates a dry-run plan (both on production and loopback). Every production mutation follows a mandatory lifecycle:

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
   During preflight, `apply` checks that each target still exists and that its `write_date` matches the pre-image. A mismatch stops the apply. The CLI saves a backup before the first write.
5. **Postcheck:** Verify the updated state immediately using read-only queries (`read` or `search_read`).
6. **Authorization Consumed:** After preflight, the CLI claims the plan once before it attempts a write. A failed or interrupted attempt still uses that approval. A new attempt requires a fresh dry-run plan and explicit approval.

An application can commit some RPC groups before a later group fails. A transport timeout can leave the last call's outcome unknown. Do not retry the full plan blindly. Read all planned IDs, compare actual values with the intended changes, and prepare a fresh plan for the verified remainder. See [partial-apply recovery](import-and-audit-workflow.md#recover-a-partially-applied-batch).

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
4. Server actions and scheduled actions: mutations on `ir.actions.server` and `ir.cron`, including `run` and `method_direct_trigger`. The `archive` command may disable a cron through the plan workflow.
5. Outbound communications: sending email, WhatsApp messages, or SMS, posting or notifying on threads, and mutating outbound message and mass mailing models.
6. Partner reconciliation: `res.partner` automated or manual merging.
7. Accounting and payroll: posting journal entries, reconciling bank statements, signing or liquidating budgets, setting payslips to `done`, and changing payment state directly or with `action_paid`.
8. System credentials: modifying `set_param` values, changing user passwords, or sending password resets (`action_reset_password`).

Server Action templates remain valid as the user's manual UI path. Keep their `WRITE_APPROVED = False` safety by default, setting it to `True` only after explicit user review.

**Allowed Production Mutations:**
Record archival (`archive`), unarchival (`unarchive`), field updates (`write`), batch updates (`write-batch`), record duplication (`copy`), and invocations of public business methods not on the deny-list are permitted exclusively through the two-phase dry-run plan and apply workflow.

**Reason:** JSON-RPC commits each call independently. Server transactions cannot be rolled back after the HTTP response completes. Denied operations carry irreversible side effects or external communication risks that cannot be undone by restoring data backups.

## Read-Only Caveats

The client-side read allowlist (`READONLY_ALLOWLIST` in `scripts/odoo_rpc.py`; its methods are listed under `call` in `SKILL.md`) inspects method names, but cannot enforce database transaction read-only isolation on the server. Computed fields with poorly designed `compute` methods or custom overrides can trigger database updates.

In addition, `export_data` is excluded from the read allowlist: [`odoo/models.py`](https://github.com/odoo/odoo/blob/17.0/odoo/models.py) routes `export_data` through `_export_rows` and `__ensure_xml_id`, which inserts rows into `ir_model_data` for records lacking external IDs. Always use `read` or `search_read` with explicit field lists for inspection.
