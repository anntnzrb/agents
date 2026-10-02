# Review an import before execution

Copy this worksheet to a private temporary directory. Replace placeholders and mark each check passed, failed, or not applicable with evidence. Do not treat this checklist as permission to write production.

## Record the scope

- Source file and checksum:
- Target database and environment:
- Delivery mode: production-targeted file for user upload by default; no production execution authorized by preparation alone.
- Final format: UTF-8 CSV by default; record any reason for another format.
- Create, update, or both:
- Requested changes and exclusions:
- Protected fields and linked records:
- Local code version and replica age:
- Final delivery machine and directory:

## Inspect provisioned code

- [ ] Resolve `runtime_path` and `addons_paths` with the skill CLI `env --json`.
- [ ] Inspect installed `base_import/models/base_import.py` and `odoo/models.py` import methods. Record relevant symbols and lines for headers, relation resolution, empty values, and error handling.
- [ ] Use `fields_get` for types, required flags, selections, and relations. Do not assume this exposes every constraint.
- [ ] Inspect inherited field definitions, defaults, related fields, inverse methods, and computed fields.
- [ ] Inspect `create`, `write`, `@api.constrains`, SQL constraints, and normalization across all relevant addons.
- [ ] Trace effects on existing related records, including contacts shared by multiple documents.
- [ ] Inspect the import view and supported options. Confirm whether rows create new records or update matched records.

## Build the mapping

For each source column, record the target technical field, conversion, omission policy, relation lookup, and ambiguity policy.

- [ ] Preserve leading zeroes and meaningful whitespace where required.
- [ ] Test omitted fields separately from empty cells.
- [ ] Resolve internal relation IDs in the target database, not a replica.
- [ ] Preserve existing identifiers. Do not fabricate values to satisfy constraints.
- [ ] Separate business-confirmed mappings from fuzzy candidates and unresolved cases.
- [ ] Keep the original source untouched and produce one final import artifact.

## Rehearse the actual path

- [ ] Use only a disposable `work` database and the skill CLI shell with `--rollback`.
- [ ] Test representative rows: valid creation, existing contact, missing optional values, ambiguity, and constraint rejection.
- [ ] Exercise the installed importer with the complete final file, headers, mapping, and options. Inspect row-level errors. An ORM-only rehearsal does not prove CSV parsing, matching, or empty-cell behavior.
- [ ] Compare every normalized row with imported values and verify protected related records before rollback.
- [ ] Record the tested checksum and options. Rerun affected checks after changing the artifact.
- [ ] Document local-only relation remapping or transient catalog fixtures without replacing target IDs in the delivered file.
- [ ] Use the ORM rehearsal template for model effects and protected invariants; adapt it to required fields and relations.
- [ ] Assert derived values and related-record invariants, not just record counts.
- [ ] Record missing catalog fixtures and production-code differences.
- [ ] Verify rollback using a fresh read after the shell exits. Database rollback does not undo external side effects; inspect and suppress those in the local rehearsal.

## Plan, verify, and deliver

- [ ] For CLI mutations, generate the existing guarded plan and obtain approval. For UI imports, agree on the actual import scope and execution path; do not pretend the CLI plan applies to a separate UI transaction.
- [ ] Compare complete normalized rows with records read back from the target database.
- [ ] On partial failure, read actual state before preparing a remainder plan or another import. Do not replay created rows blindly.
- [ ] Review privacy in descriptions and notes before sharing evidence or fixtures.
- [ ] Verify the final artifact at the requested destination, including checksum after transfer.
- [ ] Deliver row count, import options, test results, and production differences. Mark the file unverified if the actual importer rehearsal was blocked.
