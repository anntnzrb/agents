# DeepSWE live metrics

`deepswe-live` retrieves the published DeepSWE aggregate and produces deterministic JSON metrics. It is for benchmark results and model-efficiency decisions only; it is not a task, exercise, release, or trial-artifact browser.

## Invocation

Run the public entrypoint with `uv`:

```text
uv run --script <skill-dir>/scripts/cli.py --help
uv run --script <skill-dir>/scripts/cli.py <command> [options]
```

Do not use raw Python, shell wrappers, or a guessed URL. The entrypoint writes exactly one compact JSON object to stdout. Human diagnostics belong on stderr. A caller MUST parse the envelope and check `ok` before reading `data`.

## Version and source policy

The artifact base is:

```text
https://deepswe.datacurve.ai/artifacts/{benchmark_version}/
```

The canonical published aggregate is `leaderboard-live.json`; `trials.json` is optional raw input and is about 37 MB. No task, exercise, release, or trial-artifact endpoint is in scope. `latest` resolves to `DEEPSWE_DEFAULT_VERSION` when set, otherwise the single configured default `v1.1`. Explicit semantic versions `v1.1+` are accepted. Major-only values and legacy `v1` are rejected. Never infer a version from the homepage, guess a path, or combine artifacts from different versions.
For same-version reruns and new-release rollout steps, read `references/release-maintenance.md`.

## Commands

| Command | Use | Important behavior |
| --- | --- | --- |
| `fetch` | Download artifacts | Fetches the leaderboard by default; add `--trials` only when raw trials are required. Uses conditional ETag/Last-Modified cache validation. |
| `report` | Primary decision report | Summarizes model efficiency, uncertainty, extrema, and Pareto rows without re-aggregating published leaderboard rows. |
| `rank` | Order published rows | Requires an explicit metric/order in the command's supported options; retains counts and confidence-interval fields. |
| `trials` | Inspect raw trial metrics | Applies the documented default inclusion filter; report overrides explicitly. Raw scope is broader than full DeepSWE. |
| `stats` | Aggregate metric facts | Keep published values distinct from derived values. |
| `schema` | Inspect supported payload shape | Use this to adapt future releases without guessing fields. |
| `compare` | Compare local snapshots | Both snapshots MUST identify the same benchmark version. Use `--snapshot` to opt into historical local data. |

Read the command's `--help` for exact flag spelling. Common controls include `--version`, `--snapshot`, `--trials`, `--timeout`, `--allow-stale`, output/cache directory options, `--limit`, explicit quality thresholds (`--min-attempted`, `--min-tasks`, `--min-pass-at-1`), repeatable `--pareto-axis METRIC:ORDER`, and repeatable `--efficiency NAME=NUMERATOR/DENOMINATOR`.

## Freshness and failure behavior

A fresh fetch sends conditional validators when a cache entry has ETag or Last-Modified. A `304 Not Modified` reuses the exact cached artifact and preserves its provenance. HTTP, network, malformed JSON, schema, version/path, and mixed-version failures return an error envelope. The client MUST NOT silently return a last-good artifact after a failed refresh. `--allow-stale` is an explicit request to use old local data and the result MUST say that it is stale. `--snapshot` is also explicit and MUST preserve historical provenance.

## Analysis contract

- Leaderboard rows are published; do not re-aggregate them
- A configuration is identified by the tuple `model`, `reasoning_effort`, `harness`, and `config`. Never merge rows merely because their model names match
- Every ranked item should expose available `n_attempted`, `n_tasks_attempted`, score/pass fields, `ci_lo`, `ci_hi`, `ci_half`, and derived `ci_width` (`ci_hi - ci_lo`). “Confidence” means CI width only
- Default recommendations do not drop low-n or incomplete rows. Quality/sample exclusion occurs only with explicit `--min-attempted`, `--min-tasks`, or `--min-pass-at-1`
- Raw extrema are reported separately from recommendations. Derived metrics live under `derived` and never overwrite published fields
- Default Pareto means maximize `pass_at_1` while minimizing `mean_output_tokens`, `mean_cost_usd`, and `mean_agent_steps`. Repeatable `--pareto-axis METRIC:ORDER` enables an explicit alternate frontier; null axis values are excluded
- Repeatable `--efficiency NAME=NUMERATOR/DENOMINATOR` adds a derived ratio under each row. Zero denominators and invalid inputs remain null with a reason; no composite score is substituted

For raw trials, the default filter is `source='deep-swe'`, `eval_scope='full'`, and `included_in_score=true`. Every response exposes `filters_applied`, including override values. Never describe all `trials.json` rows as full DeepSWE.

## User-facing report recipe

1. Resolve one benchmark version and fetch `leaderboard-live.json`
2. Run `report`; preserve the JSON envelope and provenance
3. State whether each value is published, published raw, or derived
4. Compare configurations, not just model names; include counts and CI width
5. Present Pareto-efficient choices and raw extrema separately
6. State filters, freshness, source URL, and any explicit thresholds
7. If a fetch fails, report the error; do not fill gaps from stale data unless the user explicitly requested `--allow-stale` or `--snapshot`

The full field and provenance contract is in `references/output-contract.md` and `references/provenance.md`.
