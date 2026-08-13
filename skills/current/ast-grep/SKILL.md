---
name: ast-grep
description: Perform read-only AST-aware code search with ast-grep/sg, including structural find-usages.
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# ast-grep

## Overview

Read-only CLI search with `sg` or `ast-grep`. AST-aware grep for code exploration and SWE tasks.

## Quick start

- Prefer `sg`. Fallback `ast-grep run`. Last resort: `nix run nixpkgs#ast-grep -- run`
- Example: `sg -p 'console.log($MSG)' -l ts src`
- Files only: `sg -p 'console.log($$$)' -l ts --files-with-matches src`

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
