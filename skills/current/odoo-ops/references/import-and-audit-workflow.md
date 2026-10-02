# Prepare imports, audit CRM data, and hand off examples

Read this guide before preparing Odoo import files, classifying CRM batches, recovering partial applications, or exporting offline fixtures. Use the [safety model](safety-model.md) for permissions and [database recipes](db-recipes.md) for local rehearsal.

## Start from an adaptable template

Copy the relevant asset to a private temporary directory before editing it:

- [Import review worksheet](../assets/import-review.md): capture source inspection, field mapping, constraints, actual importer rehearsal, and delivery evidence.
- [ORM rehearsal template](../assets/orm-rehearsal.py.txt): adapt model-specific cases and invariants, then save as `rehearse.py` and run through the CLI shell with `--rollback`.
- [Offline examples template](../assets/offline-examples.json): separate provenance, inputs, observed results, expectations, catalogs, and simulated RPC responses.

Keep source discovery, constraint inspection, preservation checks, and read-back verification in every workflow. Adapt business fields and cases. Do not run the placeholder templates unchanged or treat ORM checks as proof of importer behavior.

## Establish the contract before transforming data

1. Resolve installed Odoo source and addon paths with `env --json`.
2. Inspect `fields_get`, relevant views, and installed import code for supported headers and relation resolution.
3. Inspect addon `create`, `write`, related-field inverses, normalization, and constraints. Identify changes to contacts and other linked records, not just the imported model.
4. Resolve catalog references against the target database. Include archived records when investigating missing matches; distinguish an archived exact match from no match.
5. Record the source file, target database, query domains, fields, and snapshot time privately. Do not overwrite the user's original input.

Use CSV for a user-importable flat table. Use JSON for nested catalogs, reconstructed inputs, expected outputs, and simulated RPC responses. Keep an import artifact separate from audit metadata.

## Deliver an import file without executing production writes

Interpret a request to prepare an import as a request for a production-targeted file that the user uploads, unless the user specifies another target. Preparation is not authorization to import into production.

Default to one UTF-8 CSV with verified technical headers. CSV makes conversions, quoting, and comparisons easier to inspect; do not claim that Excel is inherently unsupported or less compatible. Preserve the original spreadsheet. Use another format when the user requests it or the installed importer requires it.

Before declaring the artifact ready:

1. Rehearse the complete final file through the installed importer on `work`, including parsing, mapping, relation resolution, and ORM effects. Use rollback and inspect row-level errors.
2. Compare imported records against every normalized row and verify protected related-record values.
3. Add focused edge cases for omissions, empty cells, shared contacts, and constraints that the complete file does not cover.
4. Record the file checksum and import options. Rerun affected checks after changing the file, mapping, or options.
5. If target references are missing or different locally, document any transient fixtures or local-only remapping. Never modify production IDs in the delivered file to fit the replica.
6. Verify rollback and deliver the exact tested artifact, with row count, options, approved checks, and unresolved production differences.

If the actual importer rehearsal cannot run, label the file unverified and explain the blocker. An ORM-only test, syntax check, or guarded mutation plan is not an import dry-run. Do not guarantee production success from a replica with different code or data.

## Build a minimal import file

- Use exact technical field headers verified against the installed import implementation. For internal Many2one IDs, use `field/.id`; do not confuse this with external XML-ID resolution through `field/id`.
- Treat internal IDs as database-specific. Never carry them from a local replica into production without resolving them again.
- Omit fields whose existing values must be preserved. An omitted column and an empty cell in a present column can have different effects; test the installed importer.
- Preserve real identification on shared contacts. Related identification fields on a lead can write through to `res.partner` and trigger constraints on other opportunities for that contact.
- Do not fill a missing identity with a fabricated number or overwrite an existing identity with a placeholder just to pass import validation.
- Keep ambiguous contact information unresolved rather than choosing an arbitrary match. Record exclusions separately from the final import columns.
- Do not add redundant description or program-name columns when the requested import already supplies a resolved program reference.
- Produce one final import file unless the user requests multiple artifacts. Preserve leading zeroes, encoding, quoting, and empty-value semantics.

## Separate classification from assignment

1. Inspect structured program fields, catalog names and commercial aliases, then the relevant descriptions and internal notes.
2. Record confidence per candidate: confirmed commercial rule, exact active catalog match, archived match, ambiguous match, or unresolved.
3. Do not infer correctness from age, assignment, or a populated program field alone.
4. Preserve a known family when a concrete program cannot be resolved. A lookup failure does not establish general interest.
5. Use a general-offer flag only when the business intent is genuinely general. Inspect whether normalization clears incompatible programs only when the flag appears in incoming values.
6. When assigning a specific program, explicitly keep general-offer semantics consistent with that program.
7. Keep classification and salesperson redistribution as separate scopes. Preserve the owner unless redistribution was requested.
8. Before redistribution, verify active users, team membership, eligible program relations, and weight totals. Inspect assignment methods for no-op returns; a successful RPC call alone does not prove assignment.
9. Confirm source and stage exclusions with the business owner. Do not assume paid checkout records should follow the same assignment policy as unqualified prospects.

Do not encode deployment-specific names, IDs, equivalences, or adviser lists in this shared skill. Keep confirmed business mappings in the owning project's data or issue.

## Rehearse behavior and state the limits

1. Use only the disposable `work` database. Run the ORM rehearsal with `shell --rollback --file <temp-dir>/rehearse.py` after starting the required local workflow.
2. Check explicit values and model-derived changes, including family, program, general-offer flag, stage, owner, period, segment, and shared-contact identity where relevant.
3. If the replica lacks a production catalog entry, use a transient fixture under rollback. Mark the result as a synthetic behavioral rehearsal, not a test of actual production records.
4. Verify rollback and inspect the assertions' output. A count-only check does not prove correct relations or preserved identity.
5. State code-version and data differences between replica and production. A local success is not proof of production-code equivalence.
6. Generate the guarded plan and present explicit changes, expected derived effects, exclusions, and plan ID before requesting approval.

The CLI dry-run plan captures proposed changes and pre-images. It does not execute every production ORM constraint or side effect.

## Recover a partially applied batch

1. Stop after an application error. Preserve the plan, backup, and apply output privately.
2. Read every planned ID from the same target database, including the group whose response failed.
3. Compare each record with intended values. Separate fully applied, unchanged, conflicting, and unknown outcomes.
4. Check derived fields and protected invariants. JSON-RPC calls commit independently; an overall error does not mean zero changes persisted.
5. If reads are unavailable, report an unknown outcome rather than retrying.
6. Prepare a new guarded plan for only the verified remainder. Obtain fresh approval; do not bypass drift checks or reuse consumed authorization.
7. Read back the complete cohort after recovery. Report completed and remaining counts explicitly.

For imports, compare normalized output rows against actual created records, not just the created-record count. Check stage, relations, ownership, and protected contact values.

## Build offline examples without leaking production data

1. Sample both suspected failures and historical successes. Stratify by family, program, stage, age, and source when available; include archived cases as explicit edges.
2. Record sampling domains, limits, ordering, time windows, and omissions. ID endpoints within a time window are not a random sample or an exhaustive history.
3. Separate original payloads, partial reconstructions, and persisted results. Never invent an original webhook from a description.
4. Separate observed state from desired output. Label structurally consistent historical records as unverified business examples, not unconditional test oracles.
5. Include the minimal catalog, active flags, aliases, and assignment metadata needed to reproduce the decision. Current catalog state does not establish historical eligibility.
6. Replace personal identities and record IDs consistently across references. Remove raw descriptions, notes, contact details, and credential-bearing links. Extract only the program text needed for the case and review it for PII.
7. Include simulated creation success, assignment no-op, validation error, and creation-success/assignment-failure responses. Test that retrying assignment does not recreate the lead.
8. Parse the final JSON and check referential integrity, counts, provenance labels, and privacy. Pattern scans alone do not prove anonymization; inspect retained free text.
9. Keep private snapshots outside repositories. Share only the reviewed sanitized artifact with the authorized recipient.
10. Confirm the destination machine and directory. After an authorized transfer, compare source and destination checksums; a local path alone is not delivery to the user's workstation.

Use a compact handoff that names the artifact, issue, offline restrictions, and limits of its expected outputs. Do not make the next agent depend on production credentials.
