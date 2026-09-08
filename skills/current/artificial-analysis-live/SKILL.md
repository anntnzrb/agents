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

## Public entrypoint

With `SKILLS_DIR`:
`uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" ...`

Direct:
`uv run --script <skill-dir>/scripts/cli.py ...`

## Credentials and fetch

Before `fetch`, inject credentials by one supported path:
1. `ARTIFICIAL_ANALYSIS_API_KEY` in process environment (preferred).
2. `ARTIFICIAL_ANALYSIS_ENV_FILE` pointing to a permissions-restricted dotenv file outside the skill tree, e.g. mode `0600`.

`fetch` requires `ARTIFICIAL_ANALYSIS_API_KEY`; snapshot readers `compare`, `query`, `qa`, `stats`, `diff` do not. Process-injected values win; otherwise read the explicitly supplied external env file.

NEVER copy `.env.example` into the skill tree or generated tool home; it is a tracked template, not a secret store. NEVER pass keys through CLI or RPC. Older skill-root/ancestor `.env` discovery is transitional compatibility only, unsupported for new setups. This release has no `AA_LEGACY_DOTENV`; do not rely on it. The asset-sync owner MUST exclude skill-local `.env` and other secret files from generated tool homes; `.gitignore` controls Git tracking only and cannot enforce sync exclusion.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" fetch
```

## Model and effort comparisons

- Translate natural-language comparisons into repeatable `compare --select` selectors. Use `qa` only for single-model/provider questions.
- A selector names a published release. Without `:efforts`, include every variant observed for that release. Add comma-separated effort labels to restrict that release.
- Refresh first. Example: `compare --select "Muse Spark 1.3" --select "Astra:low,non-reasoning"`.
- Report the resolved model names, efforts, source time, and available variants. "All" means all variants in the fetched source, not every configuration a vendor offers.
- Use published release/effort metadata. Do not infer maximum effort from a bare model slug or non-reasoning from missing effort metadata.
- Missing or ambiguous families and requested efforts must be resolved before comparing. Never silently drop a requested variant.
- Preserve newly published fields without assuming their units or comparability. Do not equate per-token prices with evaluation cost per task.
- For a current dedicated benchmark, use `evaluation` and match its rows to selected canonical model slugs. Keep those scores in a separate source-scoped table. Never join only by display name or substitute another effort when a page omits one.
- A fresh API response does not establish an Intelligence Index release number. Report a benchmark version only when that source publishes it.

## Output policy

- `evaluation` parses a dedicated public benchmark page, or replays a saved HTML/RSC response with `--input`.
- Generic evaluation extraction is schema-dependent and does not guarantee parsing every benchmark page layout.
- Keep published model coding and agentic snapshot metrics (`query`, `qa`) distinct from standalone evaluation pages.
- Mark page rows `published`; mark sorting, limiting, and arithmetic `derived`; preserve source URL and scope.
- Read `references/evaluation-pages.md` before selecting an evaluation URL or comparing benchmark populations. Public evaluation URLs MUST use HTTPS.
- When freshness matters, run `fetch` immediately before `compare`, `query`, or `qa`. Default `<temp-dir>/artifacts/artificial-analysis/full-data.json` readers reject snapshots older than 24h; explicit paths intentionally represent historical data.

## Hardening

- Snapshot-reader freshness: `fresh`, `cache-revalidated`, `stale-last-good`, or explicit `snapshot`. Only explicit stale policy may return `stale:true`; explicit old input is `historical:true`, not outage-stale.
- Machine-readable rows retain additive evidence: `raw_value`, normalized value, unit, source path/field, parser/version, artifact hash; independent `value_status`, `metric_semantics_status`, and `comparison_eligibility`. Missing, placeholder, malformed, non-finite, or conflicting values NEVER become synthesized zero.
- `diagnose` is offline and inspects only explicit snapshot/cache paths. `diff --schema-aware` is opt-in and additive; legacy diff keys remain. `--json-errors` stages one compact redacted CLI error object; use `--legacy-errors` during migration. RPC remains one response per input line with existing error codes.
- Cache raw bytes and manifests are immutable, content-addressed, and redacted. `filter_agent_models.py` joins v2 endpoint rows to canonical `models` by `model_slug`; JSON preserves unknown fields, while Markdown/TSV remain fixed views.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Command routing and RPC | [references/command-routing.md](references/command-routing.md) | Choosing CLI commands, running RPC mode, or configuring cache and fallback behavior |
| Full CLI reference and flags | [README.md](README.md) | Detailed command syntax, options, and full flag definitions |
| JSON output contract and schemas | [references/output-contract.md](references/output-contract.md) | Consuming JSON envelopes, evidence fields, or freshness statuses |
| Dedicated evaluation pages | [references/evaluation-pages.md](references/evaluation-pages.md) | Running `evaluation` or replaying standalone benchmark pages |
| Troubleshooting and recovery | [references/troubleshooting.md](references/troubleshooting.md) | Resolving fetch, credential, cache, integrity, or parsing failures |
