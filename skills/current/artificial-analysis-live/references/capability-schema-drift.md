# Capability-page schema drift playbook

Use when Artificial Analysis site changes break `coding`. Goal: small, evidence-backed compatibility repair—not a new scraper or plan-quota model.

## 1. Classify failure

Run the failing command once; retain its JSON/error envelope:

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" coding --model gpt-5-6 --limit 5
```

Source boundaries:
- `fetch`, `query`, `stats`, `reasoning`: provider-leaderboard snapshot.
- `coding`: distinct Coding capability page.
- NEVER repair a capability-page failure with provider-snapshot model metadata: it lacks Coding Index task-token, task-cost, and task-time evidence.

## 2. Capture live source shape

Use public, unauthenticated evidence. Start with the page reader; use a browser if its dynamic table is absent:

```text
https://artificialanalysis.ai/models/capabilities/coding
```

Browser: close stale session; open page and inspect accessible table/metric labels; reload while recording public RSC/client resources; inspect `self.__next_f` payload for the model array and record only keys needed for normalized output; close session.

Record source URL, fetch time, observed row keys, and one redacted/public example row in the regression fixture or test comment. Primary path MUST NOT require cookies, login, or paid API access.

Optional Artificial Analysis API: cross-check identity or individual benchmark components only. Do not replace the public RSC path unless the API exposes every field used by the command and an equally stable documented contract.

## 3. Separate identity, score, optional evidence

Candidate discovery requires the smallest stable evidence:

|Evidence|Requirement|
|---|---|
|Identity|model `slug` plus name/creator when present|
|Capability score|Coding Index field: `coding_index` (legacy) or `headlineValue` (current)|
|Task metrics|optional tokens, API evaluation cost, decode time|

A scored row remains useful without optional task metrics: preserve it with `null` evidence. NEVER convert missing values to zero or drop the row solely because token/cost fields moved.

Normalize aliases at the boundary; source-specific names stay out of the public contract:

|Normalized evidence|Legacy source|Current source|
|---|---|---|
|Coding score|`coding_index`|`headlineValue`|
|Creator|`model_creators`|`modelCreator`|
|Task tokens|`tokenCounts`|`outputTokensPerTask`|
|Aggregate evaluation cost|`evalCost`|`evalCost`|
|Per-task cost|unavailable|`costPerTask`|
|Per-task decode time|unavailable|`timePerTaskSeconds`|

## 4. Preserve scope boundaries

Coding Index is its own evaluation scope. Its current headline score is the equal-weighted Coding capability index composed of Terminal-Bench v2.1 and SciCode.

- `costPerTask` and `evalCost`: Coding-evaluation/API USD evidence.
- `outputTokensPerTask`: Coding-evaluation task output, split into answer and reasoning tokens.
- `timePerTaskSeconds`: weighted decode time; excludes TTFT and other overhead.
- These values MUST NOT become ChatGPT/Codex subscription quota, messages, credits, or allowance.
- Do not synthesize missing input tokens, component scores, benchmark costs, or tool-billing fields from another page.

## 5. Repair narrowly

1. Keep the previous recognized shape.
2. Add a structural candidate predicate for the new shape; do not hard-code one container name.
3. Normalize aliases into existing output fields; add fields only for a distinct documented scope.
4. Keep output envelopes and existing keys compatible.
5. Every new numeric field: null-safe and finite. Preserve raw value, source path/field, parser/version, artifact hash, status, semantics, and comparison eligibility.
6. Preserve unknown source fields under `raw_fields`/`raw_metadata`; emit a duplicate-field diagnostic on normalization collisions.

NEVER add a second transport, broad fallback, inferred quota calculation, or silent duplicate maxing. Conflicting identities remain visible and blocked.

## 6. Regression coverage

Use only fixtures required by the changed contract:
1. Legacy coding rows with token/cost evidence.
2. Current RSC rows with `headlineValue`, task metrics, and aliases.
3. Current score-only rows proving nullable evidence.
4. Unrelated provider-leaderboard rows proving cross-page rejection.
5. Filtering and sorting on normalized output.
6. Unknown fields, finite numeric evidence, duplicate-identity diagnostics, and explicit parser/source paths when those surfaces change.

All deterministic replays run without network access. The autouse test guard denies urllib/socket calls; only `tests/test_live_smoke.py` may opt out with `RUN_LIVE_SMOKE=1`. Tests MUST fail against the previous schema assumption and pass without network access.

## 7. End-to-end verification

Run narrow tests, full offline suite, policy lint, and quick validation:

```bash
uv run --with pytest pytest -q tests/test_rsc_contract.py
uv run --with pytest pytest -q tests
uvx ruff format --check .
uvx ruff check --select ALL --ignore COM812,D203,D213 .
uv run --script "$SKILLS_DIR/skill-creator/scripts/cli.py" quick-validate "$SKILLS_DIR/artificial-analysis-live"
```

Do not run live smoke unless `RUN_LIVE_SMOKE=1` and the rotated credential is in the process environment. Successful gated smoke records only redacted source status, validator presence, hashes, parser/version, freshness, schema, shape, and diagnostics—never fixed counts, headers, or raw bodies.

## Escalation

If the live page lacks a public model array or page-level metrics, stop after preserving the diagnostic. First inspect the public page, sitemap, RSC resources, and documented API coverage. NEVER silently substitute unrelated leaderboard data or emit plausible-looking stale metrics.
