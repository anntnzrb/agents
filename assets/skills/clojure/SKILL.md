---
name: clojure
description: Develop and debug Clojure, ClojureScript, deps.edn, REPL, spec, and functional code.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Clojure Development

Functional-first Clojure with **deps.edn**, **tools.deps**, and **immutability**.

## Workflow

```
1. MODEL    -> Define data with maps, records, specs
2. COMPOSE  -> Build with pure functions, ->> threading
3. TEST     -> Write tests first (clojure.test or Kaocha)
4. VALIDATE -> clojure -M:test/run && clj-kondo --lint src
5. ITERATE  -> Refactor in REPL, keep functions pure
```

## CLI

```bash
# Project setup
clojure -Tnew app :name myuser/myapp    # New app project
clojure -Tnew lib :name myuser/mylib    # New library

# Run
clojure -M -m myapp.core                # Run -main
clojure -M:run                          # Via alias
clojure -X:run                          # Exec function

# REPL
clj                                     # Basic REPL
clojure -M:repl/rebel                   # Rebel readline

# Test
clojure -X:test/run                     # Run tests (Kaocha)
clojure -M:test -m kaocha.runner        # Alternative

# Build
clojure -T:build uber                   # Uberjar
clojure -T:build jar                    # Library jar

# Dependencies
clojure -X:deps tree                    # Dependency tree
clojure -X:deps find-versions :lib clojure.java-time/clojure.java-time
clojure -M:search/outdated              # Find outdated deps
```

## Notes

Project layout, deps.edn templates, core patterns, naming conventions, and anti-patterns live in `reference.md`.

## Engineering checks

- Normalize untrusted input once at the boundary; use `clojure.spec` only where its validation or generation pays for itself
- Preserve error context with `ex-info` and structured `ex-data`; do not catch-and-forget failures
- Keep side effects, resource ownership, cancellation, and cleanup at the edge; keep core transformations pure
- Test observable behavior and failure paths with deterministic values; avoid tests that pin private implementation shape
- Introduce helpers, protocols, or abstraction only for a concrete reuse or boundary

## Research Tools

```
# gh search code for real-world Clojure patterns
gh search code "(go-loop [" --language=clojure
gh search code "(comp (map" --language=clojure
gh search code "(s/def ::" --language=clojure
```

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Core language/project reference | `reference.md` | For data structures, idioms, errors, layout, or `deps.edn` |
| Functional patterns | `cookbook/patterns.md` | For sequences, transducers, maps, reducers, or zippers |
| Concurrency | `cookbook/concurrency.md` | For atoms, refs, agents, dynamic vars, `core.async`, futures, or promises |
| Specs | `cookbook/spec.md` | For validation, conforming, generators, or function instrumentation |
| Testing | `cookbook/testing.md` | For `clojure.test`, Kaocha, fixtures, async tests, or test.check |
| Macros | `cookbook/macros.md` | Only when a function cannot express the required compile-time transformation |
