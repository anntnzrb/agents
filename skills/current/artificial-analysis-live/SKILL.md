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

Query fresh Artificial Analysis endpoint data before answering model or provider benchmark questions. MUST run the CLI; NEVER answer from memory.

## Public entrypoint

With `SKILLS_DIR`:
`uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" ...`

Direct:
`uv run --script <skill-dir>/scripts/cli.py ...`

## Credentials and fetch

Set `ARTIFICIAL_ANALYSIS_API_KEY` in the process environment, or set `ARTIFICIAL_ANALYSIS_ENV_FILE` to point to a secure dotenv file outside the skill directory (such as permissions mode `0600`). Process environment variables take precedence over external files.

`fetch` requires `ARTIFICIAL_ANALYSIS_API_KEY`. Snapshot readers (`compare`, `query`, `qa`, `stats`, `diff`) operate offline and do not require API keys.

NEVER copy `.env.example` into the skill directory or generated tool home. Keep `.env.example` as a tracked template. Store credentials in external environment variables or external dotenv files. NEVER pass API keys via CLI flags or RPC payloads. Legacy dotenv discovery from the skill root or parent directory is unsupported. This release does not support `AA_LEGACY_DOTENV`. The asset sync process MUST exclude local `.env` files and secret files from generated tool homes.

```bash
uv run --script "$SKILLS_DIR/artificial-analysis-live/scripts/cli.py" fetch
```

## Model and effort comparisons

- Translate natural language comparisons into repeatable `compare --select` selectors. Use `qa` only for questions about a single model or provider.
- A selector names a published release. When `:efforts` is omitted, include every variant observed for that release. Append effort labels separated by commas to filter variants.
- Run `fetch` before comparing. Example: `compare --select "Muse Spark 1.3" --select "Astra:low,non-reasoning"`.
- Report resolved model names, efforts, source timestamp, and available variants. Output labeled "All" represents all variants present in the fetched snapshot.
- Rely on published release and effort metadata. Do not assume maximum effort for a bare model slug. Do not assume non-reasoning mode when effort metadata is missing.
- Resolve ambiguous model families or requested effort levels before running comparisons. MUST NOT omit a requested variant silently.
- Preserve newly published fields without assuming units or equivalence. Do not treat per-token prices as equivalent to task evaluation costs.
- For dedicated benchmark pages, use `evaluation` and match rows against canonical model slugs. Store benchmark scores in a separate table scoped to that source. Do not join rows solely by display name. Do not substitute alternative effort levels when a benchmark page omits one.
- A fresh API response does not establish an Intelligence Index release number. Report a benchmark version only when published by the source.

## Output policy

- `evaluation` parses a dedicated public benchmark page, or replays a saved HTML or RSC response with `--input`.
- Generic evaluation extraction depends on page schema and does not guarantee parsing all benchmark layouts.
- Keep published coding and agentic snapshot metrics (`query`, `qa`) separate from standalone evaluation page results.
- Label raw benchmark rows as `published`. Label sorting, filtering, and calculated metrics as `derived`. Preserve the source URL and evaluation scope.
- Read `references/evaluation-pages.md` before choosing an evaluation URL or comparing benchmark populations. Public evaluation URLs MUST use HTTPS.
- Run `fetch` immediately before `compare`, `query`, or `qa` when fresh data is required. Default readers for `<temp-dir>/artifacts/artificial-analysis/full-data.json` reject snapshots older than 24 hours. Explicit file paths read historical snapshots directly.

## Hardening

- Snapshot readers categorize freshness as `fresh`, `cache-revalidated`, `stale-last-good`, or explicit `snapshot`. Only an explicit stale policy returns `stale:true`. Explicit historical input files return `historical:true`.
- Machine-readable rows include additive evidence fields: `raw_value`, normalized value, unit, source path or field, parser version, artifact hash, `value_status`, `metric_semantics_status`, and `comparison_eligibility`. Missing, placeholder, malformed, non-finite, or conflicting values MUST NEVER convert into zero.
- `diagnose` runs offline and inspects only explicit snapshot or cache paths. The `--schema-aware` option for `diff` is opt-in and additive, preserving legacy diff keys. `--json-errors` emits a single compact redacted CLI error object; use `--legacy-errors` during migration. RPC mode returns one response per input line using existing error codes.
- Cache raw bytes and cache manifests are immutable, content-addressed, and redacted. The script `filter_agent_models.py` joins v2 endpoint rows to canonical `models` entries by `model_slug`. JSON output retains unknown fields; Markdown and TSV outputs format fixed views.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Command routing and RPC | [references/command-routing.md](references/command-routing.md) | Choosing CLI commands, running RPC mode, or configuring cache and fallback behavior |
| Full CLI reference and flags | [README.md](README.md) | Detailed command syntax, options, and full flag definitions |
| JSON output contract and schemas | [references/output-contract.md](references/output-contract.md) | Consuming JSON envelopes, evidence fields, or freshness statuses |
| Dedicated evaluation pages | [references/evaluation-pages.md](references/evaluation-pages.md) | Running `evaluation` or replaying standalone benchmark pages |
| Troubleshooting and recovery | [references/troubleshooting.md](references/troubleshooting.md) | Resolving fetch, credential, cache, integrity, or parsing failures |
