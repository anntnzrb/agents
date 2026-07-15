---
name: artificial-analysis-live
description: Compare current AI models and providers by benchmarks, speed, latency, and cost.
license: GPL-3.0-or-later
compatibility: Requires `uv` and network access.
metadata:
  author: anntnzrb
allowed-tools: ""
---

# artificial-analysis-live

AI-first skill for **fresh** Artificial Analysis endpoint data.

## Core rule

Do not answer benchmark/provider questions from stale memory. Run the tool first.

## Entry points

- With `SKILLS_DIR`: `uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" ...`
- Direct: `uv run --script <skill-dir>/scripts/cli.py ...`

## Fast path

Before fetching, copy the tracked template and set the official API key:

```bash
cp "$SKILLS_DIR/artificial-analysis-live/.env.example" "$SKILLS_DIR/artificial-analysis-live/.env"
```

`fetch` requires `ARTIFICIAL_ANALYSIS_API_KEY`; snapshot readers (`query`, `qa`,
`stats`, `diff`, `harness`, and `reasoning`) do not. The loader uses an existing
process value first, then `ARTIFICIAL_ANALYSIS_ENV_FILE`, the skill-root `.env`,
`$SKILLS_DIR/artificial-analysis-live/.env`, then the first ancestor containing
`skills/artificial-analysis-live/.env`. Do not pass keys through CLI or RPC.

The skill-local `.env` is intentionally copied by generic asset sync into every
generated tool home. Treat that replication as a secret-management risk.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" fetch
```

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

Uses `canonical_eval_token_counts` from the local snapshot — no live fetch needed. Metrics include reasoning floor (minimum reasoning share), reasoning ceiling, weighted reasoning share, and a selectivity classification. See `references/reasoning-selectivity.md` for definitions and caveats.

### stats

Snapshot counts + top providers.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" stats
```

### diff

Compare two snapshots.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" diff old.json new.json
```

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

## Output policy

- Tool output is JSON only.
- Prefer `coding` for Coding Index token composition/cost breakdown questions.
- Prefer `reasoning` for model reasoning selectivity and per-benchmark token split questions.
- Prefer `query` for provider endpoint ranking answers.
- Prefer `qa` only when user asks in plain language and speed matters.
- If data freshness is critical, run `fetch` immediately before `query`/`qa`; default `/tmp/artifacts/artificial-analysis/full-data.json` readers reject snapshots older than 24h, while explicit snapshot paths are treated as intentional historical data.

## Reliability defaults

- ETag cache + 304 reuse
- last-good fallback unless `--strict`
- sanity thresholds (`--min-endpoints`, `--min-providers`)
- extraction heuristics tolerate upstream schema key changes

## Read only what you need

- Command usage: `README.md`
- JSON envelopes and fields: `references/output-contract.md`
- Capability-page schema drift or a failed `coding` command: `references/capability-schema-drift.md`
- Other failure modes and recovery: `references/troubleshooting.md`
