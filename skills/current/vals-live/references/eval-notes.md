# Deterministic evaluation notes

The fixture suite is source-local and network-free by default. It covers all 25 required cases in `tests/fixtures/` and behavior-oriented tests for dynamic additions, arbitrary fields/categories, header permutations, model variants, release joins, extraction precedence, provenance, cache validators, stale/snapshot modes, security redaction, and exact one-object envelopes. `tests/test_live_smoke.py` is opt-in only.

Every fixture has a deterministic source URL/discovery URL, content type, release or snapshot identity, and harmless validator metadata. Raw fixture bytes are never credentials. Tests must assert output behavior rather than current catalog counts.

The five eval prompts are materialized in `evals/evals.json`:

1. List currently discovered Vals benchmarks and unknown score semantics.
2. Compare three models on current coding-related benchmarks while preserving versions and metric scopes.
3. Report code quality separately from correctness without averaging.
4. Prove a newly added benchmark is discovered without a code change.
5. Report placeholder-score drift with paths and no stale fallback.

Live smoke records evidence only and must not assert fixed current counts. No browser, screenshot, OCR, search-snippet, or cross-skill runtime dependency is permitted.
