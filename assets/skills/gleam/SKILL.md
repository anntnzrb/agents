---
name: gleam
description: Develop and debug Gleam, gleam.toml, BEAM/Erlang projects, TDD, and type-driven code.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Gleam Development

Idiomatic Gleam with **type-driven design** and **TDD**.

## Workflow

```
1. MODEL    → Define domain types first (make illegal states unrepresentable)
2. RED      → Write failing test
3. GREEN    → Minimal implementation
4. REFACTOR → Clean up, use pipelines
5. RUN      → gleam test && gleam run
```

## Research

Use `context7 docs` first, then `gh` as fallback.

## Engineering checks

- Decode external data at the boundary into domain types; model distinct concepts separately when mixing them is a bug.
- Represent expected failures with explicit `Result` error types and exhaustively handle variants; do not use `panic` as normal control flow.
- Keep effects at module boundaries and resource lifetimes explicit; keep domain logic pure where practical.
- Test observable success and error behavior with deterministic values, not private function structure.
- Add a type, helper, dependency, or abstraction only for a concrete caller or failure mode.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Research routing and code patterns | `references/guide.md` | API research or implementation guidance |

## CLI

```bash
gleam check                    # Fast type feedback (use often)
gleam test                     # Run tests
gleam run                      # Execute main
gleam format                   # Format all
gleam add pkg --dev            # Dev dependency
```
