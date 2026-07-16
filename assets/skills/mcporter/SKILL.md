---
name: mcporter
description: Manage, authenticate, inspect, and call configured MCP servers with MCPorter.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# MCPorter

Use MCPorter for generic configured-server management. Use a focused skill when one exists.

## Invocation

If `mcporter` is not on `PATH`, use:

```text
nix run github:numtide/llm-agents.nix#mcporter -- <command>
```

Pass `--config <path>` only for a non-default registry. Inspect configuration before changing it.

## Discovery and calls

Start with the least expensive query, then inspect only the chosen tool:

```text
mcporter config list
mcporter list
mcporter list <server> --brief
mcporter list <server>.<tool> --schema
mcporter list <server>.<tool> --all-parameters
mcporter call <server>.<tool> key=value
mcporter call <server>.<tool> --args '{"key":["value"]}'
```

Use `--all-parameters` when optional arguments matter. Use `key=value` or `key:value` for simple values and `--args` for objects, arrays, null, or multiline data. Do not expose secrets in output or logs.

For a deterministic health check that never begins OAuth:

```text
mcporter list <server> --status --no-oauth --exit-code
```

## Configuration and auth

```text
mcporter config get <name>
mcporter config doctor
mcporter auth <server|url>
```

Authenticate only when required. Treat missing environment substitutions and persistent 401/403 responses as prerequisites; do not invent credentials or rewrite server definitions.

## Required follow-up reads

| Need | Read | When |
|---|---|---|
| Local names, transports, and substitutions | `assets/mcporter.jsonc` | Before selecting a configured server |
| Tool arguments and output | `mcporter list <server>.<tool> --schema` | After selecting a tool |
| Server behavior | Focused skill/reference | When available |
