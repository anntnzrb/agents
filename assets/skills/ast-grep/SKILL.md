---
name: ast-grep
description: Perform read-only AST-aware code search with ast-grep/sg, including structural find-usages.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
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

## Resources

- `reference.md`: flags, strictness, selectors, output formats
- `cookbook/`: troubleshooting and recipes
