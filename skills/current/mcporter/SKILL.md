---
name: mcporter
description: Manage, authenticate, inspect, and call configured MCP servers with MCPorter.
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# MCPorter

- MCPorter SHOULD handle generic configured-server management
- Focused skills MUST take precedence when available

## Operating contract

References snapshot MCPorter 0.12.3 help captured 2026-07-16.

- Live `mcporter <command> --help` MUST override bundled snapshots
- Agents MUST read routed references before nontrivial commands
- Agents MUST discover tools before calling them
- `list --schema` documents published tool inputs, not outputs
- Agents MUST NOT invent unpublished response fields
- Observed responses MUST remain samples, not contracts
- Credentials and tool results MUST be treated as sensitive
- Secrets MUST NOT enter commands, logs, or summaries
- Authentication MUST occur only when required
- Side effects MUST have explicit task authorization

## Invocation

Agents MUST use this fallback when `mcporter` is unavailable:

```text
nix run github:numtide/llm-agents.nix#mcporter -- <command>
```

- `--config <path>` MUST target only non-default registries
- Agents MUST inspect configuration before modifying it

## Minimal workflow

- Agents SHOULD start with the least expensive query
- Agents MUST inspect only the selected tool

```text
mcporter config list
mcporter list
mcporter list <server> --brief
mcporter list <server>.<tool> --schema
mcporter list <server>.<tool> --all-parameters
mcporter call <server>.<tool> key=value
mcporter call <server>.<tool> --args '{"key":["value"]}'
```

- Agents SHOULD use `--all-parameters` when optional inputs matter
- Simple values SHOULD use `key=value` or `key:value`
- Structured values SHOULD use `--args`

For a deterministic health check that never begins OAuth:

```text
mcporter list <server> --status --no-oauth --exit-code
```

- Missing substitutions MUST block calls until resolved
- Persistent 401/403 responses MUST block calls until resolved
- Agents MUST NOT invent credentials
- Agents MUST NOT rewrite server definitions implicitly

## Required follow-up reads

| Need | Read | When |
|---|---|---|
| Exact `list`, `call`, `resource`, `auth`, `vault`, `record`, or `replay` syntax | `references/core-cli.md` | Before nontrivial use, when selecting flags, or when live help is unavailable |
| Exact generator, TypeScript emission, config, daemon, or bridge syntax | `references/admin-cli.md` | Before `generate-cli`, `inspect-cli`, `emit-ts`, `config`, `daemon`, or `serve` |
| Local names, transports, and substitutions | `assets/mcporter.jsonc` | Before selecting a configured server |
| Tool input arguments/schema | `mcporter list <server>.<tool> --schema` | After selecting a tool; inspect an explicit output schema or actual result separately |
| Server behavior | Focused skill/reference | When available |
