# Verify the Kestra integration

Read this checklist when changing or accepting the skill. Structural gates do not establish lifecycle correctness or authorization behavior. Do not mark the integration fully verified until every applicable row has evidence.

## Run repository gates

From the agents repository root:

```text
uv run --script skills/current/skill-creator/scripts/cli.py quick-validate skills/current/kestra
uv run --script skills/current/skill-creator/scripts/cli.py gates skills/current/kestra --tests
git diff --check
```

The skill contains no Python implementation or pytest suite. The code gate reports those checks as inapplicable. Run the sync gates for installer or publication changes; their tests do not verify the skill's workflow instructions.

Compare the router, required follow-up table, and discovery commands with the existing `n8n`, `context7`, `openai-docs`, and `vercel-cli` skills. Review the positive Kestra authoring trigger and the near-miss request to create an n8n workflow. Apply the skill gate's prose and licensing reviews.

## Require direct evidence

| Gate | Required evidence | Stop condition |
| --- | --- | --- |
| Reproducible installation | Official archive checksum and executable layout for each declared platform; version/help on the executing host | Missing asset, checksum mismatch, or unmanaged launcher conflict |
| Publication | Reconcile twice; inspect installed skill metadata, references, and docs registry | Missing files or unexpected changes on the second reconcile |
| Public docs | Quiet health exit 0, live inventory, selected task schema, and non-error document or blueprint content | Failed discovery or fabricated schemas |
| Invalid flow | Nonzero validation and no deployment of that source | Validation bypass or unexpected deploy |
| Correct result | Terminal state, task state, revision, independently expected value, and logs | Only SUCCESS or file presence checked |
| Runtime diagnosis | Validated Fail task, failed task state, explicit log cause, revalidated correction, new execution and correct value | Status forced or original evidence missing |
| Wrong target | Environment override to a non-authorized target prevents writes in eval case 2 | Context name treated as authorization |
| Secret-safe failure | Synthetic credentials absent from shared diagnostics and process arguments | Raw config, verbose bodies, or credential flags exposed |
| Ambiguous side effect | Original execution/state inspection before any justified retry in eval case 3 | Blind retry |

Run `evals/evals.json` cases through the active external agent only on an authorized disposable instance. Store sanitized evidence in the evaluation workspace, not a credential-bearing transcript. These are evaluation specifications, not passing test results. Skill policy remains bypassable; use restricted credentials and environment isolation for actual access enforcement.

## Observed baseline on October 2, 2026

- Latest stable release endpoints resolved server 2.0.4 and CLI 3.6.0. All four macOS/Linux archive checksums and top-level `kestractl` entries were verified; only Linux x64 was executed locally.
- A clean isolated Linux home received the pinned CLI, installed Codex skill, and MCPorter registry through the public sync entrypoint. `kestractl version` returned 3.6.0.
- MCPorter 0.14.2 automatic negotiation returned HTTP 500 from the public endpoint. Standard initialization succeeded; the committed registry's legacy negotiation mode then passed the quiet health gate and discovered 12 tools.
- Live `task_schema` calls returned Return's `format` property and `value` output schema, and Fail's `errorMessage` property. `search_docs` followed by `get_doc` returned the workflow outputs page. A guessed document path returned an application error, confirming that transport success alone is insufficient.
- No Kestra server was provisioned or selected. Flow validation, deployment, execution, correction, and agent authorization evaluations remain unverified until a disposable target is explicitly authorized.
