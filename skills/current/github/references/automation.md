# GitHub Actions and automation

**Covers:** `run`, `workflow`, `cache`, `secret`, and `variable` commands.

**Safe default:** select an explicit repository and workflow/run ID, inspect JSON
state and logs read-only, and distinguish workflow definitions from run instances.

**Write boundary:** rerun, cancel, delete, dispatch, enable/disable, cache delete,
secret/variable create/edit/delete, and environment/account changes are writes.
Require explicit authorization and re-read resulting state. Never print secret values
or pass credentials through output, fixtures, or logs.

**Adjacent handoff:** use `core.md` for host/auth/output/exit rules,
`collaboration.md` for PR checks/reviews, `release-security.md` for attestations,
and `stack-commands.md` for stack-aware CI and merge state.

## Select target and inspect state

Always bind the repository:

```text
gh run list --repo OWNER/REPO --limit 20 --json databaseId,workflowName,status,conclusion,headBranch,event,url

gh workflow list --repo OWNER/REPO --all --json id,name,state,path
```

A workflow is the YAML definition (`workflow list/view`); a run is one execution
(`run list/view/watch/logs`). Do not dispatch a workflow by guessing from a run ID,
and do not treat a workflow's enabled state as a run's success.

`gh run view RUN_ID --repo OWNER/REPO --json status,conclusion,jobs,url` reads a run.
Use `gh run view RUN_ID --log-failed` or job/step-aware output when a failure needs
root-cause evidence. Report unavailable logs instead of claiming they were inspected.

## Runs and workflows

- `gh run list`, `view`, `watch`, `download`, and `logs` are read/download paths;
  `watch` may block and `logs` may return large output. Prefer bounded JSON/log-failed
  reads in automation and separate stdout from stderr.
- `gh run rerun`, `cancel`, and `delete` mutate run state. Inspect current status and
  authorization first; re-read the run after the command returns.
- `gh workflow view WORKFLOW --repo OWNER/REPO` reads definition metadata. A workflow
  file path, ID, or exact name is safer than a fuzzy display name.
- `gh workflow run WORKFLOW --repo OWNER/REPO --ref REF [--field NAME=VALUE ...]`
  dispatches a workflow and is a remote write. Confirm workflow/ref/input values and
  authorization immediately before dispatch, then read the new run ID/state.
- `gh workflow enable/disable` changes repository automation policy. Require a clear
  request and report the resulting state.

A workflow dispatch is not a promise that the run started or succeeded. Poll/read
with `gh run view` or `gh run list` using explicit IDs and report queued/in-progress/
completed states. Do not cancel or rerun merely because a run is slow.

## Caches

`gh cache list --repo OWNER/REPO --limit N --json id,key,ref,sizeInBytes,createdAt,lastAccessedAt`
reads cache metadata. `gh cache delete ID --repo OWNER/REPO` is a write; confirm the
exact cache ID/key/ref and authorization. Do not use cache deletion as a generic CI
repair or to hide a failure. Re-read the cache listing after deletion and report if
another job recreated it.

## Secrets

`gh secret list` shows names/visibility metadata, not values. Scope the operation:

```text
gh secret list --repo OWNER/REPO --json name,updatedAt,visibility
```

Repository, environment, and organization secrets are separate targets. `gh secret
set`, `delete`, and visibility/organization operations are mutations. The CLI may
read secret input from stdin or an environment variable; never echo that source,
include it in a transcript, or store it in an eval artifact. Re-read names/metadata,
never values, after an authorized change.

## Variables

`gh variable list` reads repository, environment, or organization variable metadata.
`set` and `delete` mutate configuration and may affect builds immediately. Identify
scope and exact name, inspect current value metadata, obtain authorization, then
re-read the name/updated timestamp. Never treat a variable as a safe place for a
secret; still avoid exposing its value in logs.

## Stack-aware CI

For a stacked PR, check each layer's PR and its base/head relationship. A green lower
layer can become stale after an upstack rebase; refresh `gh stack view --json` and
PR checks after synchronization. A queued merge, required check, merge queue, or
asynchronous status belongs to the stack lifecycle; do not bypass it with a direct
`gh pr merge`. Read `stack-commands.md` before stack-aware dispatch, merge, or
recovery.

## Failure handling

Auth errors, missing workflow files, unavailable logs, canceled runs, 404s, and rate
limits are observable outcomes. Preserve run/cache/config state, use installed
`gh help` for drift, and do not silently rerun, dispatch another workflow, delete a
cache, or fall back to an API mutation.

## Official references

- [gh run](https://cli.github.com/manual/gh_run)
- [gh workflow](https://cli.github.com/manual/gh_workflow)
- [gh cache](https://cli.github.com/manual/gh_cache)
- [gh secret](https://cli.github.com/manual/gh_secret)
- [gh variable](https://cli.github.com/manual/gh_variable)
