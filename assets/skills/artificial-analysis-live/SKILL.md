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

## Output policy

- Prefer `evaluation` for a dedicated public benchmark page; use `--input` to replay a saved HTML/RSC response.
- Keep dedicated evaluation scores separate from Coding Index, Coding Agent Index, and provider-matrix data.
- Mark page rows as published and sorting/limiting/arithmetic as derived; preserve source URL and scope.
- Read `references/evaluation-pages.md` before selecting a dedicated evaluation URL or comparing benchmark populations.
- If freshness is critical, run `fetch` immediately before `query`/`qa`. Default `<temp-dir>/artifacts/artificial-analysis/full-data.json` readers reject snapshots older than 24h; explicit paths are intentional historical data.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Command selection and reliability | `references/command-routing.md` | Before choosing commands, using RPC, or relying on cache/fallback behavior |
| Full command and flag usage | `README.md` | When the fast-path commands are insufficient |
| JSON envelopes, fields, and reasoning metrics | `references/output-contract.md` | Before consuming structured output or reasoning classifications |
| Capability-page schema repair | `references/capability-schema-drift.md` | When `coding` fails after upstream drift |
| Dedicated evaluation pages | `references/evaluation-pages.md` | When using `evaluation` or separating standalone pages from composite indexes |
| Recovery | `references/troubleshooting.md` | For fetch, extraction, cache, freshness, or credential failures |
