---
name: linear
description: "Manage Linear through MCPorter: discover live tools, inspect schemas, and safely read or change data."
compatibility: Requires MCPorter configuration and Linear authentication.
---

# Linear

Linear work MUST use literal MCPorter server `linear`.

- Live schema MUST remain authoritative
- The catalog is a dated fallback snapshot
- NEVER guess against available live discovery

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Broad inventory selection | `references/tool-catalog.md` | Tool choice spans entities or remains unclear |
| Live discovery failure | `references/tool-catalog.md` | Current live schema cannot be retrieved |

Missing `mcporter`: MUST use this Nix prefix:

```text
nix run github:numtide/llm-agents.nix#mcporter --
```

## Connect and discover

- Missing SSOT config: MUST add `--config <path-to-mcporter.jsonc>`
- NEVER expose, copy, or log tokens

```text
mcporter config get linear
mcporter list linear --status --no-oauth --exit-code
mcporter list linear --brief
mcporter list linear.<tool> --schema
```

- Known/schema-sensitive tool: MUST inspect targeted live schema
- Broad selection: MUST read catalog, then inspect chosen schema
- Discovery failure: MUST read catalog and disclose drift
- NEVER invent tools, arguments, or response fields

- Auth failure: MUST run `mcporter auth linear`, then recheck status
- Persistent 401/403: MUST report missing access. NEVER write

## Calls

```text
mcporter call linear.<tool> key=value --output json
mcporter call 'linear.<tool>(arg: "value")' --output json
mcporter call linear.<tool> --args '{"id":"ENG-42","labels":["Bug"]}' --output json
mcporter call linear.<tool> body=@comment.md --output json
```

- Simple scalars SHOULD use `key=value`
- Typed literals SHOULD use function syntax
- Structured or multiline values SHOULD use `--args`
- UTF-8 files SHOULD use `key=@path`; `@@` means literal `@`
- MUST quote shell-sensitive values
- Image responses SHOULD use `--save-images <directory>`

## Safety

- Before writes: MUST resolve target and inspect write schema
- MUST apply the smallest change, then re-read
- `save_issue`: omitted `id` creates; supplied `id` updates
- Creation MUST include `title` and `team`
- `labels` replaces all labels; omission preserves them
- Nullable fields clear only with explicit `null`
- NEVER combine mutually exclusive release fields
- New comments MUST include `body` and exactly one parent
- Replies MUST use `parentId`
- Uncertain timeout: MUST read/search before retrying
- Bulk/destructive writes MUST have intent, confirmation, targeted schema
- Validation errors: MUST correct payload against live schema
- NEVER drop rejected fields silently
- Paginated reads MUST use filters/cursors and disclose boundaries
