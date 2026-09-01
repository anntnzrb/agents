---
disable-model-invocation: true
name: linear
description: "Use when Linear issues or projects must be read or changed through MCPorter."
license: AGPL-3.0-or-later
compatibility: Requires MCPorter configuration and Linear authentication.
---

# Linear

Linear work MUST use literal MCPorter server `linear`.

- Live schema MUST remain authoritative when inspected
- The catalog is a dated fallback snapshot

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Tool signature or safety notes | Relevant section of `references/tool-catalog.md` | Needed details are absent from common recipes; NEVER load the whole catalog |
| Live discovery failure | `references/tool-catalog.md` | Current live schema cannot be retrieved |

## Tool routes

This stable name index is the default discovery layer. Read only the matching catalog section when its signature or safety notes are needed.

| Domain | Tools |
| --- | --- |
| Attachments | `get_attachment`, `prepare_attachment_upload`, `create_attachment_from_upload`, `create_attachment`, `delete_attachment` |
| Agent skills | `list_agent_skills`, `get_agent_skill` |
| Comments | `list_comments`, `save_comment`, `delete_comment` |
| Cycles | `list_cycles` |
| Documents | `get_document`, `list_documents`, `save_document`, `extract_images` |
| Issues | `get_issue`, `list_issues`, `save_issue`, `list_issue_statuses`, `get_issue_status`, `list_issue_labels`, `create_issue_label` |
| Projects | `list_projects`, `get_project`, `save_project`, `list_project_labels` |
| Releases | `list_release_pipelines`, `list_releases`, `get_release`, `save_release`, `list_release_notes`, `get_release_note`, `save_release_note` |
| Diffs | `get_diff`, `list_diffs`, `get_diff_threads` |
| Milestones | `list_milestones`, `get_milestone`, `save_milestone` |
| Teams and users | `list_teams`, `get_team`, `list_users`, `get_user` |
| Documentation | `search_documentation` |
| Status updates | `get_status_updates`, `save_status_update`, `delete_status_update` |

## Common reads

These complete recipes use known inputs and SHOULD be called directly:

```text
mcporter call linear.list_issues assignee=me orderBy=updatedAt limit=5 --output json
mcporter call linear.get_issue id=ENG-42 --output json
mcporter call linear.list_projects query='<name>' limit=50 --output json
mcporter call linear.list_comments issueId=ENG-42 limit=50 --output json
mcporter call linear.list_teams query='<name>' limit=50 --output json
mcporter call linear.list_users query='<name-or-email>' limit=50 --output json
```

`list_issues` common inputs: `limit?:number=50`, `orderBy?:createdAt|updatedAt=updatedAt`, `assignee?:string|null`; `assignee=me` selects the current user. Priority values are `0=None`, `1=Urgent`, `2=High`, `3=Medium`, `4=Low`.

`--output json` selects rendering, not a response contract. Inspect returned issue records defensively for requested fields; input-schema discovery cannot validate output fields.

## Recovery

- Missing generated registry: MUST report the setup failure.
- NEVER add or substitute a registry.
- NEVER expose, copy, or log tokens

```text
mcporter list linear --status --no-oauth --exit-code
mcporter list linear --brief
mcporter list linear.<tool> --schema
```

- Select the tool from the route index; search only its catalog section for an unknown signature
- If the needed capability is absent from the index, use brief live inventory
- Inputs absent from a common recipe or catalog signature: inspect targeted live schema
- Rejected inputs or tool-not-found errors: inspect targeted live schema, then retry once
- Every mutation: MUST inspect targeted live schema
- Live discovery failure: MAY use the relevant catalog entry and MUST disclose possible drift
- NEVER invent tools, arguments, or response fields

- Run status only after a connection or authentication failure
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
