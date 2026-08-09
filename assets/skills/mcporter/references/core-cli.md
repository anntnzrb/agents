# MCPorter core CLI reference

Snapshot: MCPorter 0.12.3, captured 2026-07-16 from live `--help` output.

- Agents SHOULD use this reference when live help is unavailable
- Live `mcporter <command> --help` MUST override this snapshot

## Invocation and globals

- Agents SHOULD invoke `mcporter` directly when available
- Agents MUST use this Nix prefix otherwise:

```text
nix run github:numtide/llm-agents.nix#mcporter --
```

Top-level syntax:

```text
mcporter <command> [options]
```

Global flags:

| Flag | Meaning |
|---|---|
| `--config <path>` | Registry path; default reported by 0.12.3 is `./config/mcporter.json`. |
| `--root <path>` | Working directory for stdio servers. |
| `--log-level <debug\|info\|warn\|error>` | CLI logging level; default `warn`. |
| `--oauth-timeout <ms>` | Browser OAuth wait; default `300000`. |

- Agents SHOULD verify versions with `mcporter --version`
- Reusable instructions MUST use portable placeholders

## Select a command

| Intent | Command |
|---|---|
| Discover servers, tools, schemas, sources, or health | `list` |
| Invoke a tool | `call` |
| List or read an MCP resource | `resource` |
| Run OAuth without listing tools | `auth` |
| Seed or clear OAuth tokens non-interactively | `vault` |
| Capture MCP JSON-RPC traffic | `record` |
| Replay captured MCP JSON-RPC traffic | `replay` |

Agents MUST read `references/admin-cli.md` before administrative commands.

## `list`

```text
mcporter list [server | url] [flags]
```

Targets are a configured `<server>` name or a direct `https://...` MCP URL.

Ad-hoc server flags:

| Flag | Meaning |
|---|---|
| `--http-url <url>` | Register an HTTP server for this run. |
| `--allow-http` | Permit plain `http://` with `--http-url`. |
| `--header KEY=value` | Attach an HTTP header; repeatable. |
| `--stdio <command>` | Run an ad-hoc stdio server. |
| `--stdio-arg <value>` | Append a stdio argument; repeatable. |
| `--env KEY=value` | Inject a stdio environment variable; repeatable. |
| `--cwd <path>` | Set the stdio working directory. |
| `--name <value>` | Override the ad-hoc display name. |
| `--description <text>` | Override the ad-hoc description. |
| `--persist <path>` | Write the ad-hoc definition to an MCPorter config. |
| `--yes` | Skip persistence confirmation. |

Display and health flags:

| Flag | Meaning |
|---|---|
| `--brief` | Compact signatures for one server. |
| `--signatures` | Alias for `--brief`. |
| `--schema` | Show server-published tool schemas. |
| `--all-parameters` | Include optional parameters in tool docs. |
| `--json` | Emit a JSON summary. |
| `--status` | Check health only; omit tool docs. |
| `--exit-code` | Exit 1 if any checked server is unhealthy. |
| `--quiet` | Suppress output and imply `--exit-code`. |
| `--verbose` | Show every config source for matches. |
| `--sources` | Add source arrays to JSON without other verbose details. |
| `--timeout <ms>` | Override the per-server discovery timeout. |
| `--no-oauth` | Use cached tokens only; never start OAuth. |

Useful forms:

```text
mcporter list
mcporter list <server> --brief
mcporter list <server>.<tool> --schema --all-parameters
mcporter list <server> --status --no-oauth --exit-code
mcporter list --http-url <https-url> --schema
```

`--schema` primarily documents tool inputs published by the server. It is not evidence that a response contains any particular field.

- Agents MUST trust only explicit published output schemas
- Unspecified outputs MUST be parsed defensively

## `call`

```text
mcporter call <server.tool | url> [arguments] [flags]
```

Selectors:

| Form | Meaning |
|---|---|
| `<server>.<tool>` | Configured server and tool. |
| `https://host/mcp.<tool>` | Direct HTTP URL plus tool; registered ad hoc. |
| `--server <name>` | Override server name. |
| `--tool <name>` | Override tool name. |

Argument forms:

| Form | Meaning |
|---|---|
| `key=value` or `key:value` | Named argument with normal coercion. |
| `key=@<path>` | Read a UTF-8 string from a file; use `@@` for a literal `@`. |
| `'<server>.<tool>(key: "value")'` | Function-call syntax. Quote it for the shell. |
| `--args '<json-object>'` | Exact JSON object payload; use for arrays, objects, null, or multiline values. |
| positional values | Allowed when schema order is known. |
| `-- <values...>` | Treat all remaining tokens as literal positional values. |

Runtime flags:

| Flag | Meaning |
|---|---|
| `--timeout <ms>` | Override call timeout. |
| `--output text\|markdown\|json\|raw` | Select output rendering. |
| `--save-images <dir>` | Save image content blocks under a directory. |
| `--no-oauth` | Use cached tokens only; never start OAuth. |
| `--raw-strings` | Keep numeric-looking argument values as strings. |
| `--no-coerce` | Keep every key/value and positional argument as a raw string. |
| `--tail-log` | Stream returned log handles. |

`call` also accepts all ad-hoc server flags documented for `list`.

Safe selection sequence:

```text
mcporter list <server>.<tool> --schema --all-parameters
mcporter call <server>.<tool> key=value
mcporter call <server>.<tool> --args '{"items":["value"]}' --output json
```

- Inputs MUST conform to published schemas
- `--output json` MUST NOT imply a response contract

## `resource`

```text
mcporter resource <server> [uri] [flags]
```

Without `[uri]`, MCPorter lists resources. With `[uri]`, it reads that resource.

| Flag | Meaning |
|---|---|
| `--output auto\|text\|markdown\|json\|raw` | Choose rendering. |
| `--json` | Shortcut for `--output json`. |
| `--raw` | Shortcut for `--output raw`. |
| `--no-oauth` | Use cached tokens only; never start OAuth. |

Examples:

```text
mcporter resource <server>
mcporter resource <server> <resource-uri> --output text
```

## `auth`

```text
mcporter auth <server | url> [flags]
```

This starts authentication without listing tools.

| Flag | Meaning |
|---|---|
| `--reset` | Clear cached credentials before reauthorizing. |
| `--json` | Emit a JSON failure envelope; with `--no-browser`, also emit auth-start JSON. |
| `--no-browser` | Print the OAuth URL without launching a browser. |
| `--browser none` | Alias for `--no-browser`. |

`MCPORTER_OAUTH_NO_BROWSER=1`, `true`, or `yes` also suppresses browser launch. `auth` accepts the same ad-hoc target flags as `list`.

Authentication and `--reset` change credential state.

- Auth mutations MUST have explicit task authorization
- Agents SHOULD prefer `list <server> --status --no-oauth` for checks

## `vault`

```text
mcporter vault set <server> --tokens-file <path>
mcporter vault set <server> --stdin
mcporter vault clear <server>
```

Accepted JSON payload shape:

```json
{
  "tokens": { "access_token": "<secret>", "token_type": "Bearer" },
  "clientInfo": { "client_id": "<client-id>" }
}
```

`set` seeds credentials; `clear` removes the server entry from the OAuth vault. In 0.12.3, `vault set --help` and `vault clear --help` repeat the parent help rather than exposing additional flags.

Live tokens MUST NOT enter chat, history, fixtures, or logs.

## `record` and `replay`

```text
mcporter record <session-name> [--server <name>] [-- <command-to-run>]
mcporter replay <session-name> [--server <name>] [-- <command-to-run>]
```

`--server <name>` restricts capture or replay to one configured server. The optional command follows `--`.

MCPorter reports recordings under `<home>/.mcporter/recordings/<session-name>.ndjson`. `record` writes sensitive JSON-RPC traffic. `replay` reads that recording and can run a command against deterministic traffic.

- Recording MUST have explicit task authorization
- Session names MUST NOT contain secrets
