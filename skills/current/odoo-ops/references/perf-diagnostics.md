# Performance Diagnostics and Pre-Deploy Checks

Procedures for diagnosing slow views, frontend memory saturation, notification accumulation, and pre-deploy view collisions.

All inspections must use the standard CLI (`uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc`). Never construct custom HTTP or XML-RPC scripts. Rehearse remediations on the local replica before proposing any production mutation.

## View Latency and N+1 Compute Audit

### Symptoms
- List or Kanban views take over 10 seconds to load (`web_search_read` in browser network inspector).
- Hiding columns in the table header does not improve speed: Odoo 17 fetches every field declared across base and inherited view architectures regardless of client visibility.

### Root Causes
- Non-stored computed fields (`store=False`) executing individual queries or external calls per record.
- Odoo Studio customizations injecting computed fields into default list views with `optional="show"`.

### Benchmarking Suspect Fields
Isolate slow fields by querying a fixed batch size (e.g. 80 records) through JSON-RPC:

```text
# Baseline query with identifier only
uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc search_read crm.lead '[["user_id", "=", <user_id>]]' --fields id --limit 80

# Benchmark individual suspect fields against the baseline
uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc search_read crm.lead '[["user_id", "=", <user_id>]]' --fields 'id name' --limit 80
uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc search_read crm.lead '[["user_id", "=", <user_id>]]' --fields 'id <suspect_field>' --limit 80
```

Compare round-trip times. A delta exceeding 0.5s for 80 records indicates an N+1 compute loop or unindexed relational lookup.

### Remediation
1. In Python addon code: optimize the compute method to fetch batch data in one query (e.g. `env['model'].search([('res_id', 'in', self.ids)])`) instead of looping inside `for record in self`.
2. Where values remain static after creation, configure `store=True` with appropriate `@api.depends`.
3. In Studio views: adjust field XML to `optional="hide"` so Odoo omits the field from initial dataset fetches.

## Discuss and Notification Overload

### Symptoms
- Switching between standard forms or menus freezes the browser for several seconds, while backend database queries respond in under 300ms.
- Odoo 17 OWL framework maintains an in-memory reactive proxy for each pinned or minimized chat channel. When a partner accumulates hundreds or thousands of pinned channels (common after automated notification or bot activity), client-side reactivity stalls the main JavaScript thread.

### Read-Only Diagnostic Counts
Query accumulated notifications and channel memberships:

```text
# 1. Unread inbox notifications
uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc count mail.notification '[["res_partner_id", "=", <partner_id>], ["is_read", "=", false]]'

# 2. Pinned Discuss channels
uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc count discuss.channel.member '[["partner_id", "=", <partner_id>], ["is_pinned", "=", true]]'

# 3. Minimized (floating) chat windows
uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc count discuss.channel.member '[["partner_id", "=", <partner_id>], ["is_minimized", "=", true]]'
```

Values above 500 pinned or minimized channels indicate frontend saturation.

### Remediation
Unpin inactive channels on the local replica or prepare a dry-run mutation plan for production:
- Reset `is_pinned` to `False` and `is_minimized` to `False` on `discuss.channel.member`.
- Set `fold_state` to `'closed'`.
- Production changes must follow the dry-run plan and user approval workflow.

## Browser Client Storage Purge

When the user experiences severe UI freezing in standard browser sessions but incognito mode operates normally (<1s response), accumulated `IndexedDB`, `localStorage`, and `sessionStorage` state is the cause.

Provide this snippet for the user to paste into their browser developer console (F12):

```javascript
(async () => {
    localStorage.clear();
    sessionStorage.clear();
    if (window.indexedDB && indexedDB.databases) {
        const dbs = await indexedDB.databases();
        for (const db of dbs) {
            if (db.name) indexedDB.deleteDatabase(db.name);
        }
    }
    if (window.caches) {
        const keys = await caches.keys();
        for (const k of keys) await caches.delete(k);
    }
    location.reload();
})();
```

Reloading clears client-side cache and prompts OWL to build a clean state tree.

## Pre-Deploy Field and Model Removal Check

Before deploying an addon update (`-u`) that removes a field or model, verify that no database-level views or rules reference the target. An unmanaged reference causes view rendering failures or registry crash on startup.

### 1. Codebase Verification
Search the repository for all occurrences of the model and field names:
```text
rg "<field_name>"
rg "<model_name>"
```
Confirm zero occurrences in custom addons before checking the database.

### 2. Search Target Database Views
Inspect target database views for matching architecture strings:

```text
uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc search_read ir.ui.view '[["arch_db", "like", "<field_name>"]]' --fields 'id name model type priority active inherit_id'
```

### 3. Classify Matching Views
Retrieve external XML IDs for all matching view records:

```text
uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc external_id ir.ui.view '[<view_id_1>, <view_id_2>]'
```

- Module views (e.g. `crm_espol.*`): automatically updated when `-u` runs.
- Studio views (prefixed with `studio_customization.*`): not updated by `-u`. Studio views referencing deleted fields will fail with `invalid custom view` warnings or break UI rendering.

### 4. Check Child Inheritances
For any Studio view hit, verify whether other views inherit from it:

```text
uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc count ir.ui.view '[["inherit_id", "=", <studio_view_id>]]'
```

If children exist, address the entire inheritance chain.

### 5. Check Record Rules
Check whether any `ir.rule` references the field or model in its domain filter:

```text
uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc search_read ir.rule '[["domain_force", "like", "<field_name>"]]' --fields 'id name model_id domain_force active'
```

### 6. Studio View Removal Procedure
- On local replica: archive or drop the Studio customization to verify clean module upgrade.
- On production: `unlink` is denied by policy. Generate a dry-run plan to archive the view (`active=False`), obtain explicit user approval, and apply the plan prior to deploying the code update.
