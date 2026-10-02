---
name: webpaste
description: "Use when sharing or fetching text, screenshots, recordings, or archives via anonymous URLs; not for clipboard copying."
license: AGPL-3.0-or-later
metadata:
  author: anonymous
---

# Webpaste

Share one file or stdin anonymously. Uploads are public. Inspect content for secrets before publishing.

## Public entrypoint

```bash
uv run --script <skill-dir>/scripts/cli.py [OPTIONS] [FILE]
```

Use `webpaste` below as shorthand for this entrypoint.

## Provider choice

| Provider | Retention | Max size | Auth | Direct curl fetch | Caveats |
| --- | --- | --- | --- | --- | --- |
| pastes | 90 days | Recheck API limit | None | `--raw-url` | Text only; UTF-8 charset may be absent |
| catbox | 2 years without access | 200 MB | None | Default URL | Blank uploads, outages, datacenter filtering |
| litterbox | 72 hours | 1 GB | None | Default URL | Temporary mirror only |

Default: UTF-8 text and code go to pastes.dev; binary signatures, binary MIME types, invalid UTF-8, and NUL bytes go to Catbox. Unknown files containing UTF-8 text go to pastes.dev. Override with `--provider pastes|catbox|litterbox`. Binary content cannot use pastes.

Use pastes for text needed for fewer than 90 days. Use Catbox for binaries or longer-lived text. When durability matters, keep a host-native attachment in the chat or issue tracker as the human-facing copy, with the direct link as a curl-able mirror.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Provider limits, retention, outages, and recheck commands | `references/providers.md` | Before relying on provider policy or diagnosing upload failures |

## Common calls

```bash
webpaste shot.png
webpaste --filename recording.mov "Screen Recording.mov"
git diff | webpaste -l diff --json
webpaste --provider pastes report.md --ascii-check
webpaste --provider catbox report.md --json
webpaste --provider litterbox capture.pcap
webpaste --get <key>
webpaste --get <direct-url> --sha256 <expected-sha256> > artifact.png
webpaste --base-url http://localhost:8080/data/ src/app.py
```

## Verification and output

- Upload one file per invocation. Each request has its own `--timeout` in seconds.
- Verification downloads the returned raw URL and compares SHA-256. Empty bodies, mismatches, and 404s fail with exit `1`; no success URL is printed.
- `--no-verify` skips the download. `--ascii-check` still downloads when needed to inspect the charset.
- `--ascii-check` fails on non-ASCII text without a declared UTF-8 charset. For pastes, it rejects non-ASCII before upload because the provider does not guarantee that charset. Diagnostics list codepoints and Windows-1252 display corruption. Content is never rewritten.
- Default output is the pastes viewer URL or the Catbox/Litterbox direct URL. Use `--raw-url` for a direct pastes URL, or `--raw` for the key.
- `--json` includes `provider`, `key`, `url`, `raw_url`, `language`, `content_type`, `charset`, `bytes`, `sha256`, `verified`, and `retention`. MIME metadata is null when no download runs. Retention is a provider policy hint, not a durability guarantee; a custom pastes server can differ.
- Human output reports the served content type and charset on stderr. JSON keeps metadata on stdout.
- `--get` accepts a pastes key, a supported full URL, or a URL at the configured pastes API. It writes exact bytes without adding a newline. `--sha256` checks an expected download hash.
- `--lang` overrides text language detection. `--base-url` applies only to pastes-compatible APIs. `--no-gzip` disables pastes request compression; multipart uploads are never gzipped.
- `--filename` overrides the multipart basename, including filenames with spaces or U+202F. No accounts, keys, deletion, or media processing are used.

## Exit codes

- `0`: Success.
- `1`: Network, HTTP, provider, or post-upload verification failure.
- `2`: Invalid input, unreadable file, or pre-upload text safety failure.

## Validate

```bash
uv run --script skills/current/skill-creator/scripts/cli.py quick-validate skills/current/webpaste
uv run --script skills/current/skill-creator/scripts/cli.py gates skills/current/webpaste --tests
```

Tests replace the HTTP transport. They exercise real multipart encoding, provider routing, verification failures, charset checks, and byte-exact fetches without network access.
