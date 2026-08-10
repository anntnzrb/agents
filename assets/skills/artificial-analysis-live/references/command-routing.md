# Artificial Analysis command routing

Read this for exact command selection, invocation examples, RPC mode, or reliability behavior.

## Commands

### fetch

Get a live snapshot from the provider-leaderboard RSC source and the authenticated
official model API.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" fetch
```

The schema-v2 snapshot has one canonical model record per slug and slim provider
endpoint records joined by `model_slug`. Canonical model pricing from the official
API uses its 3:1 blend; endpoint pricing from RSC uses its 7:2:1 blend. Both are
intentional because they describe different scopes, not duplicate prices.

### query

Deterministic filter/sort over snapshot rows.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" query --model claude-opus-4-7 --sort-by speed --order desc --limit 5
```

### qa

Minimal NL command that maps question -> query args.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" qa "best provider for claude opus 4.7 by speed top 3"
```

### coding

Fetch/query the Coding Index capability page. It returns scored rows plus
Coding-evaluation task evidence when the live page publishes it.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" coding --sort-by coding --limit 10
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" coding --model gpt-5-5 --include-benchmark-counts
```

Coding Index evidence is scoped to its own evaluation, not the global
Intelligence Index or a subscription quota. Current rows may include per-task
output composition, API USD cost, and weighted decode time; optional evidence
is `null` when absent. The index is Terminal-Bench v2.1 plus SciCode; component
scores are never synthesized.


### reasoning

Profile models by reasoning selectivity — per-benchmark breakdown of answer vs thinking token splits at max effort.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" reasoning --sort-by selectivity --limit 10
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" reasoning --model minimax-m3 --benchmarks
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" reasoning --selective-only
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" reasoning --class selective_extreme
```

Uses `canonical_eval_token_counts` from the local snapshot — no live fetch needed. Metrics include reasoning floor (minimum reasoning share), reasoning ceiling, weighted reasoning share, and a selectivity classification. See `references/output-contract.md` for definitions and caveats.

### stats

Snapshot counts + top providers.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" stats
```

## diff

Compare two snapshots while keeping the legacy endpoint/provider keys:

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" diff old.json new.json
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" diff old.json new.json --schema-aware
```

Use `--schema-aware` only when model, field, metric, evidence/status,
freshness/parser/schema, duplicate, or diagnostic changes are needed. Matching
uses stable IDs first; possible renames are suggestions and never merges.

## diagnose

Inspect local health without fetching:

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" diagnose \
  --snapshot <temp-dir>/snapshot.json --cache-dir <temp-dir>/aa-cache
```

`diagnose` reports redacted snapshot/cache/schema/parser/freshness/artifact and
diagnostic state. It never performs a live refresh. The RPC command is additive
and returns one response per input line.


### Error and credential routing

- `--json-errors` stages one compact redacted CLI error object on stdout;
  `--legacy-errors` preserves human-readable stderr errors.
- RPC retains stable error codes and one response for every non-empty request.
- Set `ARTIFICIAL_ANALYSIS_API_KEY` in the process, or use
  `ARTIFICIAL_ANALYSIS_ENV_FILE` pointing to a permissions-restricted file
  outside the skill tree. Never pass keys in arguments. Older installations may
  discover a skill-root or ancestor `.env`, but that is transitional compatibility
  only, not supported setup. The asset-sync owner MUST exclude `.env` and other
  secret files from generated homes; `.gitignore` only controls Git tracking and
  cannot enforce that exclusion.
- `evaluation` accepts HTTPS URLs only. Use `--input` for local saved HTML/RSC;
  credential query parameters are redacted.

### schema

Machine-readable capability contract.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" schema
```

## RPC mode

Use when another agent/process needs JSONL envelopes.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" --mode rpc
```

## Reliability defaults

- ETag cache + 304 reuse (`freshness.mode: "cache-revalidated"`)
- last-good fallback only when explicitly enabled with
  `--stale-policy allow-last-good` or `--allow-stale`
- `--strict` remains the `error` policy alias
- sanity thresholds (`--min-endpoints`, `--min-providers`)
- explicit local inputs use `freshness.mode: "snapshot"` and `historical:true`;
  they are not outage-stale
