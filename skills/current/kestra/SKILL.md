---
name: kestra
description: Use when authoring, validating, deploying, running, or debugging Kestra workflows.
license: AGPL-3.0-or-later
---

# Operate Kestra flows

Use this skill to route a Kestra flow request through current documentation, `kestractl`, and checks of the actual execution output. Keep flow YAML and related assets in the project repository as reviewable source.

## Route the request

1. Identify the requested outcome, expected outputs, authorized instance, tenant, namespace, and whether the request allows deployment and execution.
2. Read [Instance setup and authorization](references/setup.md) before using an unfamiliar instance or CLI context.
3. Use the installed MCPorter registry entry `kestra-docs` only for public Kestra knowledge. Discover its current tools and schemas before calling it. Read [Documentation MCP](references/docs-mcp.md). Never treat it as access to the user's instance.
4. Read [Lifecycle cookbook](cookbook/lifecycle.md) for the deterministic validate, deploy, run, inspect, and diagnose pattern.
5. Author or edit the workflow in the user's project. Check it against current docs and the selected instance's compatible plugin catalog. Then validate, deploy, execute, and verify outputs as authorized.
6. Report the instance and namespace, deployed flow revision when available, execution ID, expected and observed outputs, and any remaining failure. Redact secrets and sensitive data.

Stop before deployment or execution if the target or authorization is unclear. Require explicit authorization for production writes, production execution, and destructive operations. Do not provision a server or run a business workflow unless the user asks and the required authorization is established.

Use `kestractl` directly. Do not build a REST client, installer, or wrapper for these operations. Keep credentials out of command arguments, repository files, process diagnostics, and logs. For a timeout or connection failure after a side effect may have started, inspect the original state before deciding whether another attempt is safe. Never blindly retry a non-idempotent action.

## Public entrypoint

Use the installed `kestractl` executable. Confirm its version and consult `kestractl --help` or the relevant `kestractl <group> <command> --help` before relying on a command. The current upstream command reference is [kestractl documentation](https://kestra.io/docs/kestra-cli/kestractl).

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Instance, context, and authorization setup | `references/setup.md` | Before using an unfamiliar target or context |
| Live public documentation tools and schema use | `references/docs-mcp.md` | Before consulting Kestra docs MCP |
| Validating, deploying, running, and verifying a small flow | `cookbook/lifecycle.md` | For a flow lifecycle request |
| Integration correctness gates and observed limitations | `references/validation.md` | When changing or accepting this integration |
