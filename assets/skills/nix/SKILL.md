---
name: nix
description: Develop and debug Nix, nixpkgs, flakes, NixOS, derivations, shells, and Home Manager.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Nix Development

Research-first Nix development using **parallel Context7 `docs` queries** for accurate, up-to-date information.

## Workflow

```
1. IDENTIFY  → Match question to relevant repos
2. QUERY     → Launch parallel subagents to query Context7
3. SYNTHESIZE → Combine results into actionable guidance
```

## Engineering checks

- Keep inputs and outputs explicit; validate external values at the module boundary with options, types, or assertions where a bad value would otherwise fail obscurely
- Preserve evaluation and build errors with context; do not mask failures through broad defaults or silent fallbacks
- Make package, source, and runtime ownership explicit in derivations; keep cleanup and platform assumptions local to the boundary that owns them
- Validate the user-visible result with the narrowest applicable eval, build, check, or VM test; do not test only formatting or implementation detail
- Add overlays, modules, dependencies, or abstraction only for a concrete consumer or platform need

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|Repository routing, Context7 queries, topic mapping|`reference.md`|Before selecting documentation sources|
