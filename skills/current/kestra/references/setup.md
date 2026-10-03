# Set up instance access

Use this reference when the user has not established a Kestra instance or CLI context for the task. This is a connection setup guide, not a server installation guide. Kestra server provisioning is separate and requires an explicit request.

## Confirm the target first

Ask which reachable Kestra instance, tenant, and namespace to use. Determine whether it is development, staging, or production. Confirm which actions the user authorizes. Do not infer a target from a project name, host default, prior command, or credential availability.

Before any write, inspect the active CLI context with `kestractl config show` and verify the host and tenant without displaying credentials. If the target cannot be established, stop. Do not switch to another instance to make a command work.

`config show` lists stored contexts, not environment or flag overrides. Check the effective host and tenant from those sources too. Reject credential-bearing URLs. Never accept the CLI's implicit localhost or `main` defaults as target authorization.

## Configure a context

The official CLI supports named contexts through `kestractl config add`, `kestractl config show`, and `kestractl config use`. Check the installed CLI help for exact local syntax. `config add` takes credentials in flags, so do not use it with real credentials in an agent command.

Do not put a real token or password in a command line. Command arguments may be visible to process inspection, shell history, or logs. Prefer a protected local Kestra CLI configuration file or environment variables supplied by the approved secret mechanism. Restrict access to local credential files.

Current upstream Kestra CLI documentation identifies these environment variables:

- `KESTRACTL_HOST`
- `KESTRACTL_TENANT`
- `KESTRACTL_TOKEN`
- `KESTRACTL_USERNAME`
- `KESTRACTL_PASSWORD`
- `KESTRACTL_OUTPUT`

Use either token auth or username/password auth according to the instance's edition and configured authentication. The official docs describe token auth for Enterprise and basic auth for Open Source. Check the current server configuration and CLI help. Do not assume that an edition supports a feature or access control that has not been verified.

Environment variables override values in the config file. CLI flags have higher precedence than environment variables. Avoid credential-bearing CLI flags. Version 3.6.0 masks credential headers in `--verbose` but prints bodies as-is. Leave verbose mode off when requests or responses may contain sensitive data.

The agents repository's blank `.env.example` template documents the connection variables. Harness launchers load the ignored root `.env`; direct `kestractl` invocation does not load it. Supply environment variables through the approved secret mechanism or use a private CLI context. Do not print or shell-source credential files.

## Check supported versions

The verified baseline on October 2, 2026 is Kestra server 2.0.4 and kestractl 3.6.0. The sync-managed CLI release is pinned, not updated on every invocation. Run `kestractl version` and check the selected server's reported version through its operator or authenticated instance metadata. Do not infer the server version from the CLI version.

Use `kestractl plugins installed --output json` for the connected instance's installed plugins. `kestractl plugins list 2.0.4 --edition OSS --output json` queries the public compatibility catalog, not the instance. Select the actual edition and server version. A public schema does not prove the task is installed.

See the [v3.6.0 CLI README](https://github.com/kestra-io/kestractl/tree/v3.6.0) and installed help for command behavior. Older-version compatibility is outside this integration's verified baseline.

## Apply authorization stops

- Stop if the host, tenant, namespace, or environment is ambiguous.
- Stop before deploying, executing, enabling a trigger, or changing production state until the user explicitly authorizes that action on the named target.
- Stop before deletion or other destructive actions unless the user explicitly authorizes the exact target and effect.
- Never switch to production as a fallback, silently change contexts, or treat a skill instruction as an access-control mechanism.
- Keep secrets out of flow YAML, tool calls, command arguments, logs, reports, and committed files. Redact sensitive values from output before sharing it.

Credentials and CLI contexts permit access; they do not establish the user's authorization for this task. Enforce access limits through credentials, permissions, and environment isolation. Kestra edition and configuration affect which controls are available.
