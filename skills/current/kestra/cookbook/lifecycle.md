# Validate and verify a small flow

Use this cookbook for a small, deterministic test on an explicitly authorized disposable development instance. It does not authorize server provisioning or business workflow execution. Replace angle-bracket placeholders with values the user approved. Keep the source in the project repository.

## Define independent output checks

Before authoring, state the exact output expected from each task and how to inspect it. Choose a fixed value, not a clock, random value, remote service, or mutable shared state. The official [workflow outputs guide](https://kestra.io/docs/workflow-components/outputs) documents `io.kestra.plugin.core.debug.Return` with a `format` property and a `value` output. Confirm the installed instance supports the task.

This source declares a flow output so the assertion is independent of execution status:

```yaml
id: <unique-flow-id>
namespace: <authorized-dev-namespace>
tasks:
  - id: produce
    type: io.kestra.plugin.core.debug.Return
    format: "{{ 19 * 7 - 5 }}"
outputs:
  - id: result
    type: STRING
    value: "{{ outputs.produce.value }}"
```

Expected task value and declared flow output: `"128"`, derived independently from 19 × 7 = 133, then 133 - 5 = 128. Confirm the schema and task are supported before deployment. Do not use the placeholder namespace as-is. This fixture contains no secrets; `Return` logs its rendered value.

## Reject invalid input before deployment

Create a deliberately invalid copy of the flow, such as a required flow field with no value. Keep it separate from the valid source. Run validation and confirm it fails. Do not deploy the invalid copy.

```text
kestractl flows validate <invalid-flow.yaml>
```

Record the validation error without secrets. Restore the flow source before proceeding.

## Validate and deploy the valid flow

Validate the actual source, then deploy that file to the confirmed development namespace. Use the installed CLI help to confirm flags. Avoid directory-wide deployments when a single file is sufficient.

```text
kestractl flows validate <flow.yaml>
kestractl flows deploy <flow.yaml>
```

Read back the deployed definition with `kestractl flows get <namespace> <flow-id>` and confirm its source matches the intended file. Do not treat a successful deploy response as proof that the workflow works.

Deploy fails when the flow already exists. For an authorized update to that exact flow, revalidate and use `kestractl flows deploy <flow.yaml> --override`. For flows with triggers, deployment can start work automatically. Keep test flows trigger-free; use `--disable-triggers` for a preview only when that source transformation is authorized.

## Run and check the result

Run only after authorization. Capture the returned execution ID. `--wait` waits for completion; it does not prove the expected values are correct.

```text
kestractl executions run <namespace> <flow-id> --wait --output json
kestractl executions get <execution-id> --output json
kestractl executions eval-expression <execution-id> '{{ outputs.produce.value }}' --output json
kestractl logs list <execution-id> --task-id produce --output json
```

Set a caller execution deadline before `run --wait`; version 3.6.0 has no CLI wait-timeout flag. For long work, run without `--wait` to capture the ID first, then use `executions watch <execution-id>` or bounded read-only polling. On deadline expiry, inspect the original execution. Do not rerun it.

Check terminal execution state and `produce` task state in the `run --wait` response's task runs. `executions get` normally returns execution metadata, not all task runs or output values. If task evidence is absent, do not claim the task check passed. Inspect a watch response or task-specific logs and report the remaining gap.

Version 3.6.0 `eval-expression --output json` returns a `result` string. Assert `result == "128"` and check the `produce` logs for the same rendered value. Inspect `flowRevision` from `executions get` against the revision returned by `flows get --output json`. The task value used by the declared flow output must match the independent expectation. For file-producing flows, resolve the returned storage path and use `executions download-file <execution-id> --path <storage-path> --output-file <local-file>` to inspect bytes. Do not infer artifact correctness from execution state or file presence.

## Diagnose and correct a runtime failure

For a separate negative case, use the documented `io.kestra.plugin.core.execution.Fail` task, which explicitly fails an execution. Keep it in a separate flow with no external side effects:

```yaml
id: <unique-failing-flow-id>
namespace: <authorized-dev-namespace>
tasks:
  - id: intentional_failure
    type: io.kestra.plugin.core.execution.Fail
    errorMessage: "kestra-skill intentional failure"
```

Validate this flow first. Deploy and run it only on the disposable development instance. Inspect the task state in the `run --wait --output json` response and execution metadata with `executions get`. Inspect logs with `kestractl logs list <execution-id> --task-id intentional_failure --output json`. Require `FAILED` at `intentional_failure` and the explicit error message, rather than inferring the cause from terminal status alone. The run command's exit code alone does not establish execution success.

Remove the intentional failure task and add the `Return` task and declared output from the successful example. Revalidate, then deploy with `--override` to the same authorized test flow and rerun only if the test remains safe and authorized. Inspect task state, evaluated output, revision, and logs. Assert `result == "128"`. Keep failing and corrected revisions distinguishable in source control and record both execution IDs.

## Handle uncertain outcomes safely

If a command times out or loses its connection after deployment or execution may have begun, do not repeat it automatically. Inspect the target flow and list or retrieve the original execution first. If the original operation may have caused side effects, require an explicit retry policy or renewed authorization before another run. Never force-change an execution or task-run status to manufacture success.

Report the target, deployed revision when available, execution IDs, expected and observed output checks, failure diagnosis, and any checks you could not complete. Redact sensitive values. Do not claim live-server validation unless you actually ran this workflow against an authorized server.
