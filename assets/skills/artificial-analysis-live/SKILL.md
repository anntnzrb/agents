---
name: artificial-analysis-live
description: Compare current AI models and providers by benchmarks, speed, latency, and cost.
license: GPL-3.0-or-later
compatibility: Requires `uv` and network access.
metadata:
  author: anntnzrb

---

# artificial-analysis-live

AI-first skill for **fresh** Artificial Analysis endpoint data.

## Core rule

Do not answer benchmark/provider questions from stale memory. Run the tool first.

## Entry points

- With `SKILLS_DIR`: `uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" ...`
- Direct: `uv run --script <skill-dir>/scripts/cli.py ...`

## Fast path

Provide credentials before fetching through one of the supported injection paths:

1. Set `ARTIFICIAL_ANALYSIS_API_KEY` in the process environment (preferred).
2. Set `ARTIFICIAL_ANALYSIS_ENV_FILE` to a permissions-restricted dotenv file
   outside the skill tree (for example, mode `0600`).

Do not copy `.env.example` into the skill tree or a generated tool home. It is a
tracked template, not a secret store. Do not pass keys through CLI or RPC.

`fetch` requires `ARTIFICIAL_ANALYSIS_API_KEY`; snapshot readers (`query`, `qa`,
`stats`, `diff`, `harness`, and `reasoning`) do not. Process-injected values win,
then the explicitly supplied external env file is read.

Older installations may still discover a skill-root or ancestor `.env`; that
lookup is transitional compatibility only and is not supported for new setups.
This release does not expose an `AA_LEGACY_DOTENV` switch, so do not rely on one.
The asset-sync owner MUST exclude `.env` and other secret files from generated
tool homes. `.gitignore` only controls Git tracking; it cannot enforce sync
exclusion.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" fetch
```

## Output policy

- Prefer `evaluation` for a dedicated public benchmark page; use `--input` to replay a saved HTML/RSC response
- Keep dedicated evaluation scores separate from Coding Index, Coding Agent Index, and provider-matrix data
- Mark page rows as published and sorting/limiting/arithmetic as derived; preserve source URL and scope
- Read `references/evaluation-pages.md` before selecting a dedicated evaluation URL or comparing benchmark populations
- If freshness is critical, run `fetch` immediately before `query`/`qa`. Default `<temp-dir>/artifacts/artificial-analysis/full-data.json` readers reject snapshots older than 24h; explicit paths are intentional historical data

## Released hardening modes

- Snapshot readers expose `fresh`, `cache-revalidated`, `stale-last-good`, or
  explicit `snapshot` freshness.  Only explicit stale policy may return
  `stale:true`; an explicit old input is `historical:true`, not outage-stale.
- Machine-readable rows retain additive evidence (`raw_value`, normalized value,
  unit, source path/field, parser/version, artifact hash), independent
  `value_status`, `metric_semantics_status`, and `comparison_eligibility`.
  Missing, placeholder, malformed, non-finite, or conflicting values are never
  synthesized into zero.
- `diagnose` is offline and inspects only explicit snapshot/cache paths.
  `diff --schema-aware` is opt-in and additive; legacy diff keys remain.
  `--json-errors` stages one compact redacted CLI error object; use
  `--legacy-errors` during migration. RPC remains one response per input line
  with its existing error codes.
- Cache raw bytes and manifests are immutable, content-addressed, and redacted.
  `filter_agent_models.py` joins v2 endpoint rows to canonical `models` by
  `model_slug`; JSON preserves unknown fields while Markdown/TSV stay fixed views.
- Fetch credentials come from the process environment or an explicitly supplied
  external `ARTIFICIAL_ANALYSIS_ENV_FILE`, never CLI/RPC arguments. Public
  evaluation URLs require HTTPS; use `--input` for local replay. The asset-sync
  owner MUST exclude skill-local `.env` and other secret files from generated
  homes; `.gitignore` only controls Git tracking and cannot enforce that
  exclusion.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Command selection and reliability | `references/command-routing.md` | Before choosing commands, using RPC, or relying on cache/fallback behavior |
| Full command and flag usage | `README.md` | When the fast-path commands are insufficient |
| JSON envelopes, fields, and reasoning metrics | `references/output-contract.md` | Before consuming structured output or reasoning classifications |
| Capability-page schema repair | `references/capability-schema-drift.md` | When `coding` fails after upstream drift |
| Dedicated evaluation pages | `references/evaluation-pages.md` | When using `evaluation` or separating standalone pages from composite indexes |
| Recovery | `references/troubleshooting.md` | For fetch, extraction, cache, freshness, or credential failures |
