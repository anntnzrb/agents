---
name: linear
description: "Manage Linear through MCPorter: discover live tools, inspect schemas, and safely read or change data."
compatibility: Requires MCPorter configuration and Linear authentication.
---

# Linear

Use this skill for Linear issues, projects, documents, cycles, releases, diffs, comments, and workspace
planning. Use MCPorter rather than a harness-specific integration. Treat the live server schema as the
authority: Linear's tool surface evolves.

## Connect and orient

The SSOT MCPorter config names the server `linear`. If MCPorter does not automatically load the desired
config, add `--config <path-to-mcporter.jsonc>` to every command.

```text
mcporter config get linear
mcporter list linear --status --json
mcporter list linear --brief
```

The config entry needs a reachable Linear MCP endpoint. If discovery reports authentication or access
failure, run `mcporter auth linear`, complete the OAuth flow, then repeat the status check. Never expose,
copy, or log tokens. A 401/403 after auth usually means the authenticated account lacks workspace access;
report it rather than attempting a write.

## Compact discovery and schemas

Start with `mcporter list linear --brief`, not the full schema dump. Select a candidate by capability,
then inspect only that tool before a call:

```text
mcporter list linear.save_issue --schema
mcporter list linear.save_issue --schema --all-parameters
```

Use the live name and signature returned by MCPorter; do not infer old `create_*`/`update_*` names or
maintain a static inventory. The current surface groups naturally into:

- attachments; agent skills; comments; cycles; documents and image extraction
- issues, statuses, and labels; projects, milestones, and project labels
- release pipelines, releases, and release notes; diffs and threads
- teams and users; documentation search; project/initiative status updates

For an unfamiliar request, first discover the category, then the targeted schema. Re-inspect the schema
after a validation error or when the operation has replacement, null-clearing, or mutually exclusive fields.

## Call conventions

Use JSON output for machine-readable results; use `text`, `markdown`, or `raw` only when their presentation
is specifically needed.

```text
mcporter call linear.list_issues team=ENG limit=10 --output json
mcporter call 'linear.save_issue(id: "ENG-42", priority: 1)' --output json
mcporter call linear.save_issue --args '{"id":"ENG-42","labels":["Bug"],"cycle":null}' --output json
mcporter call linear.save_comment issueId=ENG-42 body=@comment.md --output json
```

Use `key=value` or `key:value` for simple scalar arguments. Use function-call syntax for typed literals,
and `--args '<JSON object>'` for arrays, objects, `null`, or multiline content. Use `key=@path` for long
UTF-8 Markdown; `@@` starts a literal `@`. Quote shell-sensitive values. `--raw-strings` and `--no-coerce`
disable normal coercion when a schema requires a string that resembles a number or boolean. For image
responses, use `--save-images <directory>` rather than copying encoded content into context.

## Read before write

1. Resolve ambiguous team, user, project, cycle, status, label, release, or issue names with the relevant
   `list_*`/`get_*` call. Use small limits and filters; follow cursors only as needed.
2. Read the target entity immediately before mutation and inspect the targeted write schema.
3. State the intended change, affected identifiers, and whether it creates, updates, archives, or deletes.
   Ask for confirmation when the user's intent is ambiguous or the change is broad/destructive.
4. Make the smallest write. Do not batch independent writes until the first result is understood.
5. Re-read the changed entity or bounded listing and report the returned identifiers and remaining failures.

`save_*` tools may create when their `id` is omitted and update when supplied. In particular:

- `save_issue` creation requires `title` and `team`; `labels` replaces the complete label set, while
  omitted fields remain unchanged and documented nullable fields clear only when passed as `null`.
- Do not combine issue release replacement with release add/remove fields; inspect the schema for other
  mutually exclusive fields.
- `save_comment` requires `body` plus exactly one parent target when starting a thread; replies use
  `parentId`. Do not duplicate comments after an ambiguous timeout—read first.
- Deleting/archiving, attachment upload/finalization, and bulk edits require explicit user intent plus
  a fresh schema read. Preserve upload sequencing and signed-request requirements from the live schema.

## Practical workflows

**Triage:** `list_teams` → `list_issue_statuses`/`list_issue_labels` → filtered `list_issues` → review
each selected `get_issue` → `save_issue` one issue at a time → `get_issue` verification.

**Project or release planning:** resolve team/project/pipeline with list/get tools → inspect the relevant
`save_project`, `save_milestone`, `save_release`, or `save_release_note` schema → create/update → re-read
the project, milestone, or release. Do not assume milestones, pipelines, or release stages exist.

**Research and reporting:** use filtered list/get calls, `get_diff`/`get_diff_threads`, documents, and
`search_documentation`; preserve read-only mode unless the user explicitly requests a change. Summarize
scope, filters, IDs, and pagination limits so results are reproducible.

**Comments and docs:** read the issue/project/document and existing comments first; draft Markdown in a
file for long content; save once, then list/get to verify placement and content.

## Fail safely

- Unknown tool or argument: run targeted `list linear.<tool> --schema --all-parameters`; do not guess.
- Validation error: correct the payload against that schema; do not silently drop fields.
- Network timeout or uncertain write result: read the target/search for the intended result before retrying.
- Pagination or incomplete data: narrow filters, use `cursor`, and disclose the boundary.
- Auth, permission, rate-limit, or unavailable-server errors: retain the error context, avoid mutations,
  and report the concrete next step.
