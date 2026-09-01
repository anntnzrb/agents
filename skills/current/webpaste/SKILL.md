---
name: webpaste
description: "Use to upload code, diffs, logs, or text to pastes.dev via CLI or stdin with automatic syntax highlighting."
license: AGPL-3.0-or-later
metadata:
  author: anonymous
---

# Webpaste

Upload code snippets, git diffs, command logs, or text files to https://pastes.dev.

## When to use

- Share code snippets, traces, logs, or diffs via a web URL.
- Upload file contents or pipe stdin to pastes.dev.
- Inspect or retrieve existing pastes by key.

## Public entrypoint

```bash
uv run --script <skill-dir>/scripts/cli.py [OPTIONS] [FILE]
```

## Common calls

```bash
# Upload a file (language inferred from file extension)
uv run --script <skill-dir>/scripts/cli.py src/server.ts

# Pipe stdin with explicit language or shebang detection
git diff | uv run --script <skill-dir>/scripts/cli.py -l diff

# Upload with JSON output for machine consumers
uv run --script <skill-dir>/scripts/cli.py --json src/config.json

# Fetch / read raw content of an existing paste by key
uv run --script <skill-dir>/scripts/cli.py --get <key>

# Target a custom base URL
uv run --script <skill-dir>/scripts/cli.py --base-url http://localhost:8080/data/ src/app.py
```

## Options

- `FILE`: Path to local file. Reads from `stdin` if omitted or `-`.
- `-l`, `--lang`: Explicit syntax language or alias (e.g. `python`, `py`, `ts`, `diff`, `json`, `rust`, `shell`, `yaml`, `plain`).
- `--json`: Output result as JSON `{"key": "...", "url": "...", "raw_url": "..."}`.
- `--raw`: Output only the paste key.
- `--raw-url`: Output direct raw content URL.
- `--get <KEY>`: Fetch and print content of an existing paste.
- `--base-url <URL>`: API base URL (default: `https://api.pastes.dev/`).
- `--user-agent <UA>`: User-Agent header string (default: `webpaste-cli/0.1.0`).
- `--timeout <SEC>`: Network timeout in seconds (default: 15).
- `--no-gzip`: Disable request body compression.

## Supported languages

`plain`, `log`, `yaml`, `json`, `xml`, `ini`, `java`, `javascript`, `typescript`, `python`, `kotlin`, `scala`, `cpp`, `csharp`, `shell`, `ruby`, `rust`, `sql`, `go`, `lua`, `swift`, `c`, `html`, `css`, `scss`, `php`, `graphql`, `diff`, `dockerfile`, `markdown`, `proto`.

## Exit codes

- `0`: Success.
- `1`: Network, HTTP, or API error.
- `2`: File not found or invalid arguments.
