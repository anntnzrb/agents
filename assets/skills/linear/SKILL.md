---
name: linear
description: "Manage Linear through MCPorter: discover live tools, inspect schemas, and safely read or change data."
compatibility: Requires MCPorter configuration and Linear authentication.
---

# Linear

Use the literal MCPorter server name `linear` for Linear work. Treat the live server schema as
authority; do not maintain a static tool inventory.

## Connect and discover

If MCPorter does not load the SSOT config, add `--config <path-to-mcporter.jsonc>` to every command.
Never expose, copy, or log tokens.

```text
mcporter config get linear
mcporter list linear --status --no-oauth --exit-code
mcporter list linear --brief
mcporter list linear.<tool> --schema
```

Start with `mcporter list linear --brief`; inspect a targeted tool with `--schema` only when unfamiliar
or constraint-sensitive. `--schema` already shows the full schema, so do not combine it with
`--all-parameters`. Use `--all-parameters` as an intermediate expanded-signature view. `--brief` cannot
combine with schema, all-parameters, JSON, or verbose.

If auth fails, run `mcporter auth linear` and repeat status. A persistent 401/403 means the account lacks
access: report it and do not write.

## Calls

```text
mcporter call linear.<tool> key=value --output json
mcporter call 'linear.<tool>(arg: "value")' --output json
mcporter call linear.<tool> --args '{"id":"ENG-42","labels":["Bug"]}' --output json
mcporter call linear.<tool> body=@comment.md --output json
```

Use `key=value`/`key:value` for scalars, function syntax for typed literals, and `--args '<JSON object>'`
for arrays, objects, `null`, or multiline content. Use `key=@path` for UTF-8 files; `@@` is a literal
`@`. Quote shell-sensitive values. Use `--save-images <directory>` for image responses.

## Safety

- Read before write: resolve ambiguous names, read the target immediately before mutation, inspect the
  write schema, make the smallest change, then re-read to verify.
- `save_issue`: omitted `id` creates; supplied `id` updates. Creation requires `title` and `team`.
  `labels` replaces the complete set; omission preserves labels, while documented nullable fields clear
  only when passed `null`. Respect schema-defined mutually exclusive release fields.
- `save_comment`: provide `body` and exactly one parent target for a new thread; replies use `parentId`.
  After an uncertain timeout, read/search before retrying to avoid duplicates.
- Bulk or destructive writes require explicit intent/confirmation and targeted schema inspection.
- On validation errors, correct the payload against the live schema; do not silently drop fields.
- Narrow paginated reads with filters/cursors and disclose incomplete boundaries.
