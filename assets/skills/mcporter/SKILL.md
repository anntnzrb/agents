---
name: mcporter
description: Manage MCP servers, tool calls, endpoints, auth/OAuth, and configuration through MCPorter.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# MCPorter

Use MCPorter to manage MCP servers, tool calls, configuration, and OAuth—not as a generic all-server workflow.

Define `mcporter` once per shell:

`mcporter() { nix run github:numtide/llm-agents.nix#mcporter -- "$@"; }`

Then use `mcporter <command>` below.

## Discovery

```text
mcporter list
mcporter list <server> --brief
mcporter list <server>.<tool> --schema
```

Start with `list <server> --brief`. For an unfamiliar or constraint-sensitive call, inspect only
`<server>.<tool>` with `--schema`; it already returns the full schema. Use
`list <server> --all-parameters` instead when an expanded signature is enough. Do not combine
`--brief` with `--schema`, `--all-parameters`, `--json`, or `--verbose`; do not combine `--schema`
with `--all-parameters`.

## Calls

```text
mcporter call <server.tool> key=value
mcporter call '<server.tool(arg: "value")>'
mcporter call <server.tool> --args '{"key":["value"]}'
```

Use `key=value` for simple values, function-call syntax for typed literals, and `--args '<JSON object>'`
for arrays, objects, `null`, or multiline content. Use `key=@file` for file content; `@@` begins a
literal `@`. Quote shell-sensitive values.

## Configuration and health

```text
mcporter config list
mcporter config get <name>
mcporter config doctor
mcporter list <server> --status --no-oauth --exit-code
```

Use the status command and its exit code as the cached-auth health check. Inspect config before changing
it; use `config doctor` for configuration failures.

## Authentication

```text
mcporter auth <server|url>
```

Authenticate only when the server requires OAuth or reports an auth failure. Never expose, copy, or log
tokens; report persistent 401/403 responses rather than attempting writes.
