---
disable-model-invocation: true
name: artificial-analysis-live
description: "Use when comparing current AI models or providers by benchmarks, speed, latency, quality, or price."
license: AGPL-3.0-or-later
compatibility: Requires `uv` and network access.
metadata:
  author: anntnzrb

---

# artificial-analysis-live

AI-first skill for **fresh** Artificial Analysis endpoint data.

MUST run the tool before answering benchmark/provider questions; NEVER use stale memory.

## Commands

With `SKILLS_DIR`:
`uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" ...`

Direct:
`uv run --script <skill-dir>/scripts/cli.py ...`

## Credentials and fetch

Before `fetch`, inject credentials by one supported path:
1. `ARTIFICIAL_ANALYSIS_API_KEY` in process environment (preferred).
2. `ARTIFICIAL_ANALYSIS_ENV_FILE` pointing to a permissions-restricted dotenv file outside the skill tree, e.g. mode `0600`.

`fetch` requires `ARTIFICIAL_ANALYSIS_API_KEY`; snapshot readers `query`, `qa`, `stats`, `diff`, `harness`, `reasoning` do not. Process-injected values win; otherwise read the explicitly supplied external env file.

NEVER copy `.env.example` into the skill tree or generated tool home; it is a tracked template, not a secret store. NEVER pass keys through CLI or RPC. Older skill-root/ancestor `.env` discovery is transitional compatibility only, unsupported for new setups. This release has no `AA_LEGACY_DOTENV`; do not rely on it. The asset-sync owner MUST exclude skill-local `.env` and other secret files from generated tool homes; `.gitignore` controls Git tracking only and cannot enforce sync exclusion.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" fetch
```

## Output policy

- `evaluation` preferred for a dedicated public benchmark page; `--input` replays a saved HTML/RSC response and is used for local replay.
- Keep dedicated evaluation scores separate from Coding Index, Coding Agent Index, and provider-matrix data.
- Mark page rows `published`; mark sorting, limiting, and arithmetic `derived`; preserve source URL and scope.
- Read `references/evaluation-pages.md` before selecting a dedicated evaluation URL or comparing benchmark populations. Public evaluation URLs MUST use HTTPS.
- When freshness matters, run `fetch` immediately before `query`/`qa`. Default `<temp-dir>/artifacts/artificial-analysis/full-data.json` readers reject snapshots older than 24h; explicit paths intentionally represent historical data.

## Hardening

- Snapshot-reader freshness: `fresh`, `cache-revalidated`, `stale-last-good`, or explicit `snapshot`. Only explicit stale policy may return `stale:true`; explicit old input is `historical:true`, not outage-stale.
- Machine-readable rows retain additive evidence: `raw_value`, normalized value, unit, source path/field, parser/version, artifact hash; independent `value_status`, `metric_semantics_status`, and `comparison_eligibility`. Missing, placeholder, malformed, non-finite, or conflicting values NEVER become synthesized zero.
- `diagnose` is offline and inspects only explicit snapshot/cache paths. `diff --schema-aware` is opt-in and additive; legacy diff keys remain. `--json-errors` stages one compact redacted CLI error object; use `--legacy-errors` during migration. RPC remains one response per input line with existing error codes.
- Cache raw bytes and manifests are immutable, content-addressed, and redacted. `filter_agent_models.py` joins v2 endpoint rows to canonical `models` by `model_slug`; JSON preserves unknown fields, while Markdown/TSV remain fixed views.

## Required follow-up reads

- Command selection/reliability: `references/command-routing.md`; before choosing commands, using RPC, or relying on cache/fallback behavior.
- Full command/flag usage: `README.md`; when fast-path commands are insufficient.
- JSON envelopes, fields, reasoning metrics: `references/output-contract.md`; before consuming structured output or reasoning classifications.
- Capability-page schema repair: `references/capability-schema-drift.md`; when `coding` fails after upstream drift.
- Dedicated evaluation pages: `references/evaluation-pages.md`; when using `evaluation` or separating standalone pages from composite indexes.
- Recovery: `references/troubleshooting.md`; for fetch, extraction, cache, freshness, or credential failures.
