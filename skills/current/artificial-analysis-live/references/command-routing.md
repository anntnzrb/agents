# Artificial Analysis command routing

Scope: exact command selection, invocation examples, RPC mode, reliability behavior.

## Commands

### fetch
Fetch a live snapshot from the provider leaderboard RSC source and authenticated official model API.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" fetch
```

Schema-v2 snapshot structure:
- One canonical model record per slug.
- Slim provider endpoint records joined by `model_slug`.
- Official API canonical model pricing uses a 3:1 blend.
- RSC endpoint pricing uses a 7:2:1 blend.

### compare
Compare canonical models across published releases and reasoning efforts without duplicating provider endpoints:

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" compare \
  --select "Muse Spark 1.3" --select "Astra:low,non-reasoning"
```

Run `fetch` first for current questions. Each repeated `--select` names a release, optionally followed by `:effort,effort`. An unrestricted release selects all observed variants. Family matching uses published release names and slugs. Ambiguous names and missing requested efforts raise errors.

Translate user natural-language requests into selectors. Use `compare` for multi-model comparison. Discover unknown effort labels from the source.
For dedicated benchmark comparisons, discover variants with `compare`, then read the benchmark with `evaluation`. Match exact canonical model slugs, preserve page metric names, and report missing variants. Keep page results separate from API composite scores.
### query
Filter and sort snapshot rows deterministically.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" query --model claude-opus-4-7 --sort-by speed --order desc --limit 5
```

### qa
Translate a natural-language question into query arguments.

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

Generic evaluation extraction depends on page schema structure. Dedicated page scores remain separate from official model snapshot metrics.

### stats
Display snapshot counts and top providers.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" stats
```

### diff
Compare snapshots while preserving legacy endpoint and provider keys:

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" diff old.json new.json
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" diff old.json new.json --schema-aware
```

Pass `--schema-aware` to inspect model, field, metric, evidence/status, freshness/parser/schema, duplicate, or diagnostic changes. Matching uses stable IDs first. Treat possible renames as suggestions without merging records.

### diagnose
Inspect local health without fetching:

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" diagnose \
  --snapshot <temp-dir>/snapshot.json --cache-dir <temp-dir>/aa-cache
```

Reports redacted snapshot, cache, schema, parser, freshness, artifact, and diagnostic state. Runs locally without network requests. RPC mode returns one response per input line.

### Error and credential routing
- Pass `--json-errors` to write one compact redacted error object to stdout. Pass `--legacy-errors` for human-readable stderr errors.
- RPC returns stable error codes and one response per non-empty request.
- Set `ARTIFICIAL_ANALYSIS_API_KEY` in the environment or set `ARTIFICIAL_ANALYSIS_ENV_FILE` to a restricted file path outside the skill tree. Pass credentials through environment variables rather than command arguments.
- Treat skill-root or ancestor `.env` files as transitional compatibility.
- Asset-sync processes MUST exclude `.env` and secret files when generating homes.
- Provide HTTPS URLs to `evaluation`, or use `--input` for local saved HTML/RSC files. Credential query parameters are redacted automatically.

### schema
Output the machine-readable capability contract.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" schema
```

## RPC mode
Use RPC mode when another process consumes JSONL envelopes.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" --mode rpc
```

## Reliability defaults
- ETag cache and 304 reuse use `freshness.mode: "cache-revalidated"`.
- Fall back to the last-good snapshot when `--stale-policy allow-last-good` or `--allow-stale` is enabled.
- `--strict` serves as the alias for the `error` policy.
- Enforce sanity thresholds with `--min-endpoints` and `--min-providers`.
- Local inputs set `freshness.mode: "snapshot"` and `historical: true`.
