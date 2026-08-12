# MCPorter admin/generation CLI

Snapshot: 0.12.3; live `--help` captured 2026-07-16. Agents MUST read this reference before administrative commands; live help overrides this snapshot.

```text
mcporter <command> --help
mcporter config <subcommand> --help
```

0.12.3: Agents MUST NOT probe `mcporter daemon <action> --help`; use `mcporter daemon --help`.

## Command selection

|Intent|Command|
|---|---|
|Standalone CLI|`generate-cli`|
|Generated-CLI metadata|`inspect-cli`|
|TypeScript types/client|`emit-ts`|
|Server config inspect/mutation|`config`|
|Keep-alive process management|`daemon`|
|One MCP server over daemon-managed servers|`serve`|

Agents MUST read `references/core-cli.md` before core commands and authentication.

## generate-cli

```text
mcporter generate-cli [server | command | url] [flags]
```

Targets: `<server>` configured server; `<command|url>` infer an inline stdio/HTTP server; `--server <name|json>` server name, HTTP URL, or JSON definition; `--command <value>` inline stdio command or HTTP URL; `--from <artifact>` regenerate from an existing generated CLI.

Flags: `--output <path>` TypeScript template; `--bundle [path]` bundled JavaScript (optional path); `--compile [path]` Bun-compiled binary (optional path); `--runtime node|bun` generated-code runtime; `--bundler rolldown|bun` JavaScript bundler; `--timeout <ms>` discovery/call timeout; `--minify`/`--no-minify` bundle minification; `--include-tools a,b` only listed tools; `--exclude-tools a,b` omit listed tools; `--dry-run` with `--from`, print regeneration command.

MUST select exactly one target form. Included/excluded tools MUST originate from discovery. `--output`, `--bundle`, and `--compile` write artifacts. `--dry-run` prints a regeneration command only with `--from`.

## inspect-cli

```text
mcporter inspect-cli <artifact> [flags]
```

`--json` embedded metadata as JSON; `--format text|json` output format. SHOULD inspect metadata before replacing generated artifacts.

## emit-ts

```text
mcporter emit-ts <server> --out <file> [flags]
```

`--mode types|client` declarations only or client plus declarations; `--out <path>` required primary `.ts`/`.d.ts`; `--types-out <path>` declaration path with `--mode client`; `--include-optional` optional schema fields in signatures; `--json` JSON summary. Tool input schemas drive generated signatures. Generated types MUST NOT imply unpublished response fields.

## config

```text
mcporter config <command> [options]
```

`list` merged local/imported servers; `get` one server definition; `add` local definition; `remove` local definition; `import` inspect/copy editor/tool imports; `login` auth; `logout` delete cached OAuth credentials; `doctor` validate config/token-cache prerequisites.

MUST inspect with `list`, `get`, and `doctor` first. Config additions MUST use `add --dry-run` before writing. Config mutations MUST have explicit task authorization.

### config list

```text
mcporter config list [options] [filter]
```

`--json` JSON instead of ANSI text; `--source local|import` restrict to local definitions or imported entries; `[filter]` positional substring match on server names.

### config get

```text
mcporter config get <name> [--json]
```

Shows transport, headers, and environment overrides; `--json` emits JSON. Secrets and resolved substitutions MUST be redacted.

### config add

```text
mcporter config add [options] <name> [target]
```

Transport/target flags: `--url <https-url>` HTTP/S base URL and implies HTTP transport; `--command <binary>` stdio executable and implies stdio transport; `--stdio <binary>` alias for `--command`; `--transport http|sse|stdio` force/validate transport; repeatable `--arg <value>` append stdio argument; `--` forward all remaining tokens as stdio arguments.

Definition flags: `--description <text>` summary; repeatable `--env KEY=value` environment entry; repeatable `--header KEY=value` HTTP header; `--token-cache-dir <path>` OAuth token persistence directory; `--client-name <name>` OAuth client identifier; `--oauth-client-id <id>` preregistered OAuth client ID; `--oauth-client-secret-env <env>` client secret environment variable; `--oauth-token-endpoint-auth-method <method>` token auth method, e.g. `client_secret_post`; `--oauth-redirect-url <url>` custom redirect URL; `--auth <strategy>` force auth type, e.g. `oauth`; `--copy-from <import:name>` seed from imported definition.

Persistence flags: `--persist <config-path>` alternate MCPorter config; `--scope home|project` config scope, default `project`; `--dry-run` print proposed entry without writing.

Secrets SHOULD use environment-variable references. Secret values MUST NOT enter arguments or committed config.

### config remove

```text
mcporter config remove <name>
```

Deletes the named definition from the active MCPorter config. MUST verify definition and active scope first.

### config import

```text
mcporter config import <kind> [options]
```

Imports include Cursor, Claude, Codex, and other kinds recognized by the installed version. `--path <file>` read a specific import config; `--filter <substring>` filter names before listing/copying; `--copy` write filtered entries to local config; `--json` JSON instead of text. Read-only inspections MUST omit `--copy`; import kinds MUST come from CLI or existing config.

### config login/logout

```text
mcporter config login <name|url> [options]
mcporter config logout <name>
```

`login` delegates to `mcporter auth`, including ephemeral/ad-hoc flags, `--reset`, `--no-browser`, and `--browser none`. `MCPORTER_OAUTH_NO_BROWSER=1`, `true`, or `yes` supplies the no-browser default. `logout` deletes the OAuth-enabled server's token-cache directory. Both mutate credential state.

### config doctor

```text
mcporter config doctor
```

Validates config files, warns about missing token caches, and prints config locations. SHOULD be preferred for read-only prerequisite checks.

## daemon

```text
mcporter daemon <start|status|stop|restart>
```

`start` starts the keep-alive daemon and auto-detects keep-alive servers; `status` reports daemon/active-server state; `stop` shuts down daemon and all managed servers; `restart` stops any running daemon and starts a fresh instance.

Parent flags from `mcporter daemon --help`: `--foreground` current-process debugging; `--log` daemon logging in MCPorter's state directory; `--log-file <path>` daemon stdout/stderr file; `--log-servers <csv>` calls only for listed servers, implies `--log`.

Logs can contain sensitive activity. In 0.12.3, action-level `--help` is not a help operation and may start, stop, or restart the daemon. MUST run `status` before state-changing daemon actions.

## serve

```text
mcporter serve [--servers a,b,c] [--stdio | --http <port>]
```

Exposes daemon-managed keep-alive servers as one MCP server. `--servers <csv>` restricts named servers; `--stdio` serve over stdio, default; `--http <port>` Streamable HTTP on `/mcp` and `/mcp/<server>`; `--host <host>` HTTP bind host, default `127.0.0.1`.

`--stdio` and `--http` are alternatives. Non-loopback binding changes network exposure, MUST have explicit task authorization, and requires authentication assessment.
