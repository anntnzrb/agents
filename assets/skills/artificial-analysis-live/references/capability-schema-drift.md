# Capability-page schema drift playbook

Use this runbook when a capability command (`coding` today) fails after Artificial Analysis changes its site. The objective is a small, evidence-backed compatibility repair — not a new scraper or a plan-quota model.

## 1. Classify the failure

Run the failing command once and retain its JSON/error envelope:

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" coding --model gpt-5-6 --limit 5
```

Then identify the source boundary:

- `fetch`, `query`, `stats`, and `reasoning` use the provider-leaderboard snapshot.
- `coding` fetches the distinct Coding capability page.
- Never repair a capability-page failure by treating provider-snapshot model metadata as capability results. It lacks Coding Index task-token, task-cost, and task-time evidence.

## 2. Capture the live source shape

Use public, unauthenticated evidence only. Start with the page reader and then use a browser if its dynamic table is absent:

```text
https://artificialanalysis.ai/models/capabilities/coding
```

Browser workflow:

1. Close any stale browser session.
2. Open the capability page and inspect its accessible table/metric labels.
3. Reload while recording public RSC/client resources.
4. Inspect the page's `self.__next_f` payload for the model array and record only the keys needed for normalized output.
5. Close the browser session.

Record the source URL, fetch time, observed row keys, and one redacted/public example row in the regression fixture or test comment. Do not require cookies, login, or paid API access for the primary path.

The optional Artificial Analysis API may be useful for cross-checking identity or individual benchmark components. Do not replace the public RSC path with it unless it exposes every field used by the command and has an equally stable documented contract.

## 3. Separate identity, score, and optional evidence

Build candidate discovery around the smallest stable evidence:

| Evidence | Requirement |
| --- | --- |
| Identity | model `slug` plus name/creator when present |
| Capability score | the page's Coding Index field (`coding_index` legacy, `headlineValue` current) |
| Task metrics | optional tokens, API evaluation cost, and decode time |

A scored row remains useful if optional task metrics are absent. Preserve it with `null` evidence; never turn missing values into zero and never drop the row solely because token/cost fields moved.

Normalize aliases at the boundary. Keep source-specific names out of the public contract:

| Normalized evidence | Legacy source | Current source |
| --- | --- | --- |
| Coding score | `coding_index` | `headlineValue` |
| Creator | `model_creators` | `modelCreator` |
| Task tokens | `tokenCounts` | `outputTokensPerTask` |
| Aggregate evaluation cost | `evalCost` | `evalCost` |
| Per-task cost | unavailable | `costPerTask` |
| Per-task decode time | unavailable | `timePerTaskSeconds` |

## 4. Preserve scope boundaries

The Coding Index is its own evaluation scope. Its current headline score is the equal-weighted Coding capability index composed of Terminal-Bench v2.1 and SciCode.

- `costPerTask` and `evalCost` are Coding-evaluation/API USD evidence.
- `outputTokensPerTask` is Coding-evaluation task output, split into answer and reasoning tokens.
- `timePerTaskSeconds` is weighted decode time; it excludes TTFT and other overhead.
- These values MUST NOT be converted to ChatGPT/Codex subscription quota, messages, credits, or allowance.
- Do not synthesize missing input tokens, component scores, benchmark costs, or tool-billing fields from a different page.

## 5. Repair narrowly

1. Keep the previous recognized shape.
2. Add a structural candidate predicate for the new shape rather than hard-coding one container name.
3. Normalize aliases into existing output fields; add new fields only when they carry a distinct documented scope.
4. Keep output envelopes and existing keys compatible.
5. Make every new numeric field null-safe.
6. Update `references/output-contract.md` in the same change.

Avoid adding a second transport, a broad fallback, or an inferred quota calculation unless the first-party source requires it.

## 6. Add regression coverage

Every schema repair needs these fixtures:

1. legacy coding rows with token/cost evidence;
2. current RSC rows with `headlineValue`, task metrics, and aliases;
3. current score-only rows, proving they are retained with nullable evidence;
4. unrelated provider-leaderboard rows, proving cross-page data is rejected;
5. filtering and sorting on the normalized output.

The test must fail against the previous schema assumption and pass without network access.

## 7. Verify end to end

Run the narrow tests, the full skill test suite, and one fresh public live command:

```bash
uv run --with pytest pytest -q tests/test_rsc_contract.py
uv run --with pytest pytest -q tests
uv run python -m py_compile lib/artificial_analysis/cli.py
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" coding --model gpt-5-6 --sort-by cost --limit 5
uv run --script "$SKILLS_DIR/skill-creator/scripts/cli.py" quick-validate "$SKILLS_DIR/artificial-analysis-live"
```

A successful live command is necessary but insufficient: confirm that it returns expected scored models, documents missing optional evidence as `null`, and keeps scope labels intact.

## Escalation rule

If the live page no longer contains a public model array or page-level metrics, stop after preserving the diagnostic and first inspect the public page, sitemap, RSC resources, and documented API coverage. Do not silently substitute unrelated leaderboard data or emit plausible-looking stale metrics.
