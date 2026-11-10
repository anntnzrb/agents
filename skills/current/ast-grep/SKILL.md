---
name: ast-grep
description: "Use when searching code with ast-grep or sg, matching AST structural syntax patterns, not for plain regex search."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# ast-grep

## Overview

AST-aware, read-only search for code exploration.

## Public entrypoint

Run `uv run --script <skill-dir>/scripts/cli.py run <args>`. The wrapper requires Bun and runs the version pinned in `UPSTREAM.json`.

## Quick start

- Search: `uv run --script <skill-dir>/scripts/cli.py run -p 'console.log($MSG)' -l ts src`
- Files only: add `--files-with-matches`.

For maintenance, update `UPSTREAM.json` to a stable release at least 14 days old. Confirm the npm package version matches the upstream tag and review changes in the tracked npm directory.

## Guardrails

- Read-only: never use `--rewrite`, `-r`, `--update-all`, or `--interactive`
- Stdin requires `--lang`

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Flags and matching semantics | `reference.md` | For strictness, selectors, output, globs, config, or stdin |
| Basic patterns | `cookbook/basics.md` | For common read-only find-usage recipes |
| Advanced patterns | `cookbook/advanced.md` | For selectors, relationships, or tighter scope control |
| Recovery | `cookbook/troubleshooting.md` | When parsing, language detection, quoting, or binary resolution fails |
