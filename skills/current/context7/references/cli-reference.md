# Context7 CLI Reference

Reference guide for all commands, flags, environment variables, and authentication options in the `ctx7` CLI invoked via `bun x`.

## Table of Contents

- [Execution](#execution)
- [Documentation commands](#documentation-commands)
  - [library](#library)
  - [docs](#docs)
- [Skills management commands](#skills-management-commands)
- [Agent configuration commands](#agent-configuration-commands)
  - [setup](#setup)
  - [remove](#remove)
- [Authentication commands](#authentication-commands)
  - [whoami](#whoami)
  - [login and logout](#login-and-logout)
- [Environment variables](#environment-variables)
- [Telemetry](#telemetry)

---

## Execution

Execute commands on demand with `bun x`:

```bash
# Verify CLI execution
bun x ctx7@latest --help
```

---

## Documentation commands

### library

Search the Context7 index to resolve a library name to its Context7 library ID.

```bash
bun x ctx7@latest library <name> [<query>] [--json]
```

Arguments:
- `name`: Package or library name. Prefer official names with proper punctuation (e.g. `"Next.js"` not `"nextjs"`, `"Three.js"` not `"threejs"`).
- `query`: Optional natural language query describing what to look up. Directly affects candidate ranking.

Options:
- `--json`: Output matching libraries as structured JSON array.
- `-h, --help`: Display help for library command.

### docs

Query targeted code examples and prose documentation snippets for a resolved library ID.

```bash
bun x ctx7@latest docs <libraryId> <query> [--json]
```

Arguments:
- `libraryId`: Fully qualified Context7 ID starting with `/` (e.g. `/facebook/react`, `/reactjs/react.dev`, `/vercel/next.js/v14.3.0`).
- `query`: Focused, single-topic natural language question.

Options:
- `--json`: Output snippets as structured JSON (`codeSnippets` and `infoSnippets`).
- `-h, --help`: Display help for docs command.

---

## Skills management commands

Context7 CLI can search, install, suggest, and generate agent skills:

```bash
# Install skills from a repository
bun x ctx7@latest skills install /owner/repo

# Install a specific skill
bun x ctx7@latest skills install /owner/repo skill-name

# Search the skills registry
bun x ctx7@latest skills search <keywords>

# Auto-suggest skills based on project dependencies
bun x ctx7@latest skills suggest

# List installed skills
bun x ctx7@latest skills list

# Uninstall a skill
bun x ctx7@latest skills remove <name>

# Generate a custom skill with AI (requires login)
bun x ctx7@latest skills generate
```

---

## Agent configuration commands

### setup

Configure Context7 integration for coding agents and editor harnesses.

```bash
# Interactive setup
bun x ctx7@latest setup

# Skip mode prompt
bun x ctx7@latest setup --mcp            # MCP server mode
bun x ctx7@latest setup --cli            # CLI + Skills mode

# Target specific agent (MCP mode)
bun x ctx7@latest setup --claude
bun x ctx7@latest setup --cursor
bun x ctx7@latest setup --opencode

# Target specific agent install location (CLI + Skills mode)
bun x ctx7@latest setup --cli --claude       # Claude Code (~/.claude/skills)
bun x ctx7@latest setup --cli --cursor       # Cursor (~/.cursor/skills)
bun x ctx7@latest setup --cli --universal    # Universal (~/.agents/skills)
bun x ctx7@latest setup --cli --antigravity  # Antigravity (~/.agent/skills)

# Additional flags
bun x ctx7@latest setup --project        # Configure current workspace only
bun x ctx7@latest setup --yes            # Skip confirmation prompts
bun x ctx7@latest setup --api-key <key>  # Pass existing API key
bun x ctx7@latest setup --oauth          # Use OAuth endpoint (MCP mode only)
```

### remove

Uninstall or remove Context7 configurations from coding agents.

```bash
# Target specific agents
bun x ctx7@latest remove --cursor
bun x ctx7@latest remove --claude --project

# Remove both setup modes explicitly
bun x ctx7@latest remove --cursor --all

# Remove only one setup mode
bun x ctx7@latest remove --cursor --cli
bun x ctx7@latest remove --claude --mcp
```

---

## Authentication commands

### whoami

Check current login status, user name, email, and teamspace.

```bash
bun x ctx7@latest whoami
```

### login and logout

Manage Context7 account authentication.

```bash
# Log in via browser
bun x ctx7@latest login

# Log in without opening browser (prints verification URL and device code)
bun x ctx7@latest login --no-browser

# Log out
bun x ctx7@latest logout
```

---

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `CONTEXT7_API_KEY` | Context7 API key for authentication and higher rate limits | Unset |
| `CTX7_TELEMETRY_DISABLED` | Set to `1` to disable anonymous telemetry collection | Unset |

---

## Telemetry

The CLI collects anonymous usage data to improve documentation coverage. To disable:

```bash
# Single command
CTX7_TELEMETRY_DISABLED=1 bun x ctx7@latest docs /facebook/react "useEffect examples"

# Shell configuration
export CTX7_TELEMETRY_DISABLED=1
```
