# Evaluation notes

Deterministic fixtures under `tests/fixtures/` cover separately shaped cases 1-25: dynamic/current release and category discovery, added/reordered columns, variants, rename/archive, absent optionals, placeholders, explicit/ambiguous/malformed numbers, duplicate identities, mixed releases, 200/304/404/cache failures, embedded JSON/RSC/table fallbacks, unknown semantics/categories, JavaScript-only delivery, and partial extraction.

Behavior tests assert one compact stdout object, string `schema_version:"1"`, exact release identity, per-value raw/source paths, published-versus-derived separation, unknown-field retention, comparison blockers, no fake zeros, no implicit stale/older-release fallback, validator requests, redaction, and snapshot freshness. Property-style tests use arbitrary category/task/model/column names and column permutations rather than a permanent catalog enum.

The live smoke test is opt-in only (`RUN_LIVE_SMOKE=1`), evidence-oriented, and must not assert today's fixed row/category count. It records redacted URLs, release, hashes, parser, timestamps, freshness, and warnings; credentials/cookies are never captured.
