# MCPorter admin and generation CLI reference

Snapshot: MCPorter 0.12.3, captured 2026-07-16 from live `--help` output.

- Agents MUST read this reference before administrative commands
- Live help MUST override this snapshot when different

```text
mcporter <command> --help
mcporter config <subcommand> --help
```

- Agents MUST NOT probe `daemon <action> --help` in 0.12.3
- Agents MUST use `mcporter daemon --help` instead

## Select a command

| Intent | Command |
|---|---|
| Generate a standalone CLI | `generate-cli` |
| Inspect generated CLI metadata | `inspect-cli` |
| Emit TypeScript types or a client | `emit-ts` |
| Inspect or mutate server configuration | `config` |
| Manage keep-alive processes | `daemon` |
| Expose daemon-managed servers as one MCP server | `serve` |

Agents MUST read `references/core-cli.md` before core commands.

## `generate-cli`

```text
mcporter generate-cli [server | command | url] [flags]
```

Target selection:

| Form | Meaning |
|---|---|
| `<server>` | Configured server. |
| `<command\|url>` | Infer an inline stdio or HTTP server. |
| `--server <name\|json>` | Server name, HTTP URL, or JSON definition. |
| `--command <value>` | Inline stdio command or HTTP URL. |
| `--from <artifact>` | Regenerate from an existing generated CLI. |

Flags:

| Flag | Meaning |
|---|---|
| `--output <path>` | Write the TypeScript template. |
| `--bundle [path]` | Emit bundled JavaScript; path is optional. |
| `--compile [path]` | Emit a Bun-compiled binary; path is optional. |
| `--runtime node\|bun` | Runtime for generated code. |
| `--bundler rolldown\|bun` | Bundler for JavaScript output. |
| `--timeout <ms>` | Discovery and call timeout. |
| `--minify` / `--no-minify` | Enable or disable bundle minification. |
| `--include-tools a,b` | Generate only the comma-separated tools. |
| `--exclude-tools a,b` | Omit the comma-separated tools. |
| `--dry-run` | With `--from`, print the regeneration command. |

- Agents MUST select exactly one target form
- Included or excluded tools MUST originate from discovery

`--output`, `--bundle`, and `--compile` write artifacts. `--dry-run` only prints a regeneration command when used with `--from`.

## `inspect-cli`

```text
mcporter inspect-cli <artifact> [flags]
```

| Flag | Meaning |
|---|---|
| `--json` | Print embedded metadata as JSON. |
| `--format text\|json` | Choose output format. |

Agents SHOULD inspect metadata before replacing generated artifacts.

## `emit-ts`

```text
mcporter emit-ts <server> --out <file> [flags]
```

| Flag | Meaning |
|---|---|
| `--mode types\|client` | Emit declarations only or a client plus declarations. |
| `--out <path>` | Required primary `.ts` or `.d.ts` output. |
| `--types-out <path>` | Declaration output path for `--mode client`. |
| `--include-optional` | Include optional schema fields in signatures. |
| `--json` | Print a JSON summary. |

Tool input schemas drive generated signatures.

Generated types MUST NOT imply unpublished response fields.

## `config`

```text
mcporter config <command> [options]
```

| Intent | Subcommand |
|---|---|
| Show merged local/imported servers | `list` |
| Inspect one server definition | `get` |
| Add a local server definition | `add` |
| Delete a local definition | `remove` |
| Inspect or copy editor/tool imports | `import` |
| Run auth | `login` |
| Delete cached OAuth credentials | `logout` |
| Validate config and token-cache prerequisites | `doctor` |

- Agents MUST inspect with `list`, `get`, and `doctor` first
- Config additions MUST use `add --dry-run` before writing
- Config mutations MUST have explicit task authorization

### `config list`

```text
mcporter config list [options] [filter]
```

| Flag/argument | Meaning |
|---|---|
| `--json` | Emit JSON instead of ANSI text. |
| `--source local\|import` | Restrict to local definitions or imported entries. |
| `[filter]` | Positional substring match against server names. |

### `config get`

```text
mcporter config get <name> [--json]
```

This shows transport, headers, and environment overrides. `--json` emits the entry as JSON.

Secrets and resolved substitutions MUST be redacted from output.

### `config add`

```text
mcporter config add [options] <name> [target]
```

Target and transport flags:

| Flag | Meaning |
|---|---|
| `--url <https-url>` | Set HTTP/S base URL and imply HTTP transport. |
| `--command <binary>` | Set stdio executable and imply stdio transport. |
| `--stdio <binary>` | Alias for `--command`. |
| `--transport http\|sse\|stdio` | Force and validate a transport. |
| `--arg <value>` | Append a stdio argument; repeatable. |
| `--` | Forward every remaining token as a stdio argument. |

Definition flags:

| Flag | Meaning |
|---|---|
| `--description <text>` | Human-readable summary. |
| `--env KEY=value` | Environment entry; repeatable. |
| `--header KEY=value` | HTTP header; repeatable. |
| `--token-cache-dir <path>` | Override OAuth token persistence directory. |
| `--client-name <name>` | Customize OAuth client identifier. |
| `--oauth-client-id <id>` | Use a preregistered OAuth client ID. |
| `--oauth-client-secret-env <env>` | Read client secret from an environment variable. |
| `--oauth-token-endpoint-auth-method <method>` | Set token auth method, such as `client_secret_post`. |
| `--oauth-redirect-url <url>` | Set a custom redirect URL. |
| `--auth <strategy>` | Force auth type, such as `oauth`. |
| `--copy-from <import:name>` | Seed from an imported definition. |

Persistence flags:

| Flag | Meaning |
|---|---|
| `--persist <config-path>` | Write to an alternate MCPorter config. |
| `--scope home\|project` | Select home or project config; default `project`. |
| `--dry-run` | Print the proposed entry without writing. |

- Secrets SHOULD use environment-variable references
- Secret values MUST NOT enter arguments or committed config

### `config remove`

```text
mcporter config remove <name>
```

Deletes the named definition from the active MCPorter config.

Agents MUST verify the definition and active scope first.

### `config import`

```text
mcporter config import <kind> [options]
```

Supported imports include Cursor, Claude, Codex, and other import kinds recognized by the installed version.

| Flag | Meaning |
|---|---|
| `--path <file>` | Read a specific import config file. |
| `--filter <substring>` | Filter names before listing or copying. |
| `--copy` | Write filtered entries into local config. |
| `--json` | Emit JSON instead of text. |

- Read-only inspections MUST omit `--copy`
- Import kinds MUST come from CLI or existing config

### `config login` and `logout`

```text
mcporter config login <name|url> [options]
mcporter config logout <name>
```

`login` delegates to `mcporter auth`, including its ephemeral/ad-hoc flags, `--reset`, `--no-browser`, and `--browser none`. `MCPORTER_OAUTH_NO_BROWSER=1`, `true`, or `yes` supplies the no-browser default.

Agents MUST read `references/core-cli.md` before authentication.

`logout` deletes the token cache directory for the OAuth-enabled server. Both commands mutate credential state.

### `config doctor`

```text
mcporter config doctor
```

Validates config files, warns about missing token caches, and prints config locations.

Agents SHOULD prefer `doctor` for read-only prerequisite checks.

## `daemon`

```text
mcporter daemon <start|status|stop|restart>
```

| Action | Effect |
|---|---|
| `start` | Start the keep-alive daemon and auto-detect keep-alive servers. |
| `status` | Report daemon and active-server state. |
| `stop` | Shut down the daemon and all managed servers. |
| `restart` | Stop any running daemon and start a fresh instance. |

Parent-level flags reported by `mcporter daemon --help`:

| Flag | Meaning |
|---|---|
| `--foreground` | Run in the current process for debugging. |
| `--log` | Enable daemon logging in MCPorter's state directory. |
| `--log-file <path>` | Write daemon stdout/stderr to a specific file. |
| `--log-servers <csv>` | Log calls only for listed servers; implies `--log`. |

Logs can contain sensitive activity. In 0.12.3, action-level `--help` is not a help operation and may start, stop, or restart the daemon.

Agents MUST run `status` before state-changing daemon actions.

## `serve`

```text
mcporter serve [--servers a,b,c] [--stdio | --http <port>]
```

This exposes daemon-managed keep-alive servers as one MCP server.

| Flag | Meaning |
|---|---|
| `--servers <csv>` | Restrict the bridge to named keep-alive servers. |
| `--stdio` | Serve over stdio; default mode. |
| `--http <port>` | Serve Streamable HTTP on `/mcp` and `/mcp/<server>`. |
| `--host <host>` | HTTP bind host; default `127.0.0.1`. |

`--stdio` and `--http` are alternatives. Binding to a non-loopback host changes network exposure.

- Non-loopback binding MUST have explicit task authorization
- Agents MUST assess authentication before non-loopback exposure
