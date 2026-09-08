# Artificial Analysis command routing

Scope: exact command selection, invocation examples, RPC mode, reliability behavior.

## Commands

### fetch
Live snapshot from provider-leaderboard RSC source + authenticated official model API.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" fetch
```

Schema-v2 snapshot:
- one canonical model record per slug;
- slim provider-endpoint records joined by `model_slug`;
- official-API canonical model pricing uses a 3:1 blend;
- RSC endpoint pricing uses a 7:2:1 blend.
These blends are intentional: different scopes, not duplicate prices.

### query
Deterministic filter/sort over snapshot rows.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" query --model claude-opus-4-7 --sort-by speed --order desc --limit 5
```

### qa
Minimal natural-language command: question to query args.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" qa "best provider for claude opus 4.7 by speed top 3"
```

### evaluation
Extract model scores from a dedicated public benchmark page or replayed HTML/RSC file:

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" evaluation \
  https://artificialanalysis.ai/evaluations/<benchmark-slug> --sort-by score --order desc --limit 10
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" evaluation --input <temp-dir>/evaluation.html
```

Generic evaluation extraction is schema-dependent and does not guarantee parsing every benchmark page layout. Dedicated page scores remain separate from official model snapshot metrics.

### stats
Snapshot counts + top providers.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" stats
```

### diff
Compare snapshots while keeping legacy endpoint/provider keys:

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" diff old.json new.json
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" diff old.json new.json --schema-aware
```

Use `--schema-aware` only for needed model, field, metric, evidence/status, freshness/parser/schema, duplicate, or diagnostic changes. Matching uses stable IDs first; possible renames are suggestions only and never merges.

### diagnose
Inspect local health without fetching:

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" diagnose \
  --snapshot <temp-dir>/snapshot.json --cache-dir <temp-dir>/aa-cache
```

Reports redacted snapshot/cache/schema/parser/freshness/artifact + diagnostic state. Never performs a live refresh. RPC command is additive and returns one response per input line.

### Error and credential routing
- `--json-errors`: stages one compact redacted CLI error object on stdout; `--legacy-errors`: preserves human-readable stderr errors.
- RPC retains stable error codes and one response for every non-empty request.
- Set `ARTIFICIAL_ANALYSIS_API_KEY` in the process, or use `ARTIFICIAL_ANALYSIS_ENV_FILE` pointing to a permissions-restricted file outside the skill tree. Never pass keys in arguments.
- Older installations may discover a skill-root or ancestor `.env`: transitional compatibility only, unsupported setup.
- Asset-sync owner MUST exclude `.env` and other secret files from generated homes. `.gitignore` controls Git tracking only and cannot enforce that exclusion.
- `evaluation` accepts HTTPS URLs only. Use `--input` for local saved HTML/RSC; credential query parameters are redacted.

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
- ETag cache + 304 reuse: `freshness.mode: "cache-revalidated"`.
- Last-good fallback only when explicitly enabled with `--stale-policy allow-last-good` or `--allow-stale`.
- `--strict` remains the `error` policy alias.
- Sanity thresholds: `--min-endpoints`, `--min-providers`.
- Explicit local inputs use `freshness.mode: "snapshot"` and `historical:true`; they are not outage-stale.
