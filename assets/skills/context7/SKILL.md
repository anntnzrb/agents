---
name: context7
description: Retrieve current library, framework, SDK, API, CLI, and cloud-service documentation with the official ctx7 CLI. Use for Context7/ctx7 requests, API syntax, setup/configuration, version-specific changes, library-specific debugging, code examples, and any question where current docs matter. Uses `bun x ctx7@latest` only; no MCP, no installs, no persistent setup.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Context7

Use the official `ctx7` CLI for current documentation and code examples. This skill is CLI-only and read-only: no MCP, no setup, no installs, no generated skills, no persistent login flows.

## Entry point

```text
bun x ctx7@latest library <name> "<user question>"
bun x ctx7@latest docs <libraryId> "<user question>"
```

There is no installation step. Do not run `npm install -g`, `ctx7 setup`, `ctx7 skills install`, `ctx7 skills generate`, `ctx7 skills remove`, or `ctx7 login` from this skill.

## Workflow

1. If the user provides a Context7 library ID (`/org/project`, `/org/project/version`, or `/websites/...`), skip lookup.
2. Otherwise resolve the library with `bun x ctx7@latest library <name> "<full user question>"`.
3. Pick the best ID by exact name, description relevance, snippet count, source reputation, benchmark score, and requested version.
4. Fetch docs with `bun x ctx7@latest docs <libraryId> "<full user question>"`.
5. Answer from the fetched docs. If Context7 fails, state the failure and do not silently pretend the answer is current.

Do not run more than three Context7 commands for one user question unless the user explicitly asks for broader exploration.

## Query discipline

- Use the user's full intent as the query; specific questions rank better than keywords.
- Do not send API keys, passwords, personal data, proprietary code, or secrets to Context7.
- Use `--json` only when structured parsing is materially useful.
- Missing `CONTEXT7_API_KEY` is not a problem by itself. Public docs queries work without auth at lower rate limits.

## Optional read-only skill registry lookup

Only if the user explicitly asks about Context7 skills/registry, you MAY use read-only text/JSON commands such as skill search/info/list-style lookups. Do not install, generate, remove, configure, authenticate persistently, or modify agent state.

## Required follow-up reads

| Need                                         | Read                      | When                                                                  |
| -------------------------------------------- | ------------------------- | --------------------------------------------------------------------- |
| CLI command details, auth, errors, telemetry | `references/cli.md`       | Before debugging command failures or using JSON/auth-related behavior |
| Worked docs lookup examples                  | `cookbook/docs-lookup.md` | When choosing IDs, versions, or query wording                         |

## Quick examples

```text
bun x ctx7@latest library react "hooks useState"
bun x ctx7@latest docs /reactjs/react.dev "useState hook behavior"
bun x ctx7@latest library nextjs "app router server actions" --json
bun x ctx7@latest docs /vercel/next.js "app router server actions" --json
```
