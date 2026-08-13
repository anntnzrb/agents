---
name: deepswe-live
description: Analyze published DeepSWE benchmark metrics and model-efficiency results with deterministic versioned JSON data.
license: AGPL-3.0-or-later
compatibility: Requires uv; network is needed only for fetch.
metadata:
  author: anntnzrb

---

# deepswe-live

Use for DeepSWE benchmark scores, model-efficiency comparisons, confidence intervals, trial summaries, or reproducible metrics reports. Answers MUST contain metrics/results only: NEVER fetch or discuss task, exercise, release, trajectory, or trial-artifact content.

## Rules

- MUST run the CLI for current-data questions; NEVER substitute remembered values.
- stdout MUST contain one compact JSON object; read diagnostics only from stderr and NEVER parse logs as results.
- `scope.value_status`: `published` | `published_raw` | `derived`; NEVER present derived values as published scores.
- `latest` resolves only through `DEEPSWE_DEFAULT_VERSION`, otherwise code default `v1.1`. Accept explicit semantic versions `v1.1+`; reject major-only versions and NEVER fetch legacy `v1`.
- Use only artifact endpoints documented in `references/provenance.md`; NEVER guess versions from a homepage or mix versions.
- Network, HTTP, malformed, schema, or mixed-version failure is an error. NEVER silently use last-good cache; stale local data requires `--allow-stale` or explicit `--snapshot`.

## CLI

```text
uv run --script <skill-dir>/scripts/cli.py <command> [options]
```

`fetch` acquires the published leaderboard; `--trials` opts into raw trials. Use `report` for the primary model-efficiency decision and `--snapshot <path>` for a historical local artifact. No command downloads task/exercise/release/trial-artifact records.

Routing: current model-efficiency → `report` (fetch first when freshness matters); published leaderboard order → `rank` with explicit metric and order; published aggregates → `stats` or `schema`; included raw-trial metrics → `trials` with explicit filter overrides as needed; two snapshots → `compare` (both MUST use the same benchmark version); artifact acquisition → `fetch` (`--trials` opt-in because raw file is large).

CLI output: `ok`, `schema_version`, `command`, and `data` or `error`. Check `ok` before reading results. Successful metrics responses require `data.scope` and `data.provenance`.

## Analysis

- Published leaderboard rows are authoritative; NEVER re-aggregate.
- Preserve config identity as `model + reasoning_effort + harness + config`; NEVER merge tiers/configurations.
- Keep raw extrema separate from recommendations. Recommendations have no quality/sample exclusion by default; apply `--min-attempted`, `--min-tasks`, or `--min-pass-at-1` only on user request.
- Every ranked row carries available attempted/task counts, score/pass fields, `ci_lo`, `ci_hi`, `ci_half`, and derived `ci_width = ci_hi - ci_lo`. “Confidence” means CI width, not correctness probability.
- Pareto defaults: maximize `pass_at_1`; minimize `mean_output_tokens`, `mean_cost_usd`, and `mean_agent_steps`. `report --pareto-axis metric:order` selects an alternate frontier; NEVER invent a composite score.
- `report --efficiency name=numerator/denominator` adds a derived ratio. Zero denominators and missing/non-finite inputs remain null with a reason.

## Required reads

- Command choice and version/cache behavior → `references/command-routing.md`, before selecting a command or handling fetch/cache results.
- JSON envelope and metric fields → `references/output-contract.md`, before consuming output or writing a report.
- URLs, freshness, validators, and labels → `references/provenance.md`, before citing data or describing published/raw/derived values.
- Provenance, same-version refreshes, or new releases → `references/release-maintenance.md` when upstream reruns models, publishes `v1.12`/`v2.0`, or the default release must move.
- Complete flags/examples → `README.md` when fast routing does not answer the invocation question.

## Evidence and comparison controls

Existing v1 envelope and raw row fields remain authoritative. Hardened responses add under `metrics` or a row’s `derived` object:

- `raw_value`, `normalized_value` (null when unavailable);
- `unit`, `normalization`, `source_path`, `parser`, `parser_version`, and artifact hash/raw-byte reference when available;
- `value_status`: `published` | `published_raw` | `derived`;
- `metric_semantics_status`; `comparison_eligibility`: `eligible` | `blocked`; explicit `blocked_reasons`.

Missing, placeholder, malformed, non-finite, out-of-range, unknown, or ambiguous values remain visible and NEVER silently become zero. Derived CI width and efficiency NEVER overwrite published fields.

`--strict-semantics` blocks values lacking known metric semantics. `compare --strict-compare` additionally proves compatible artifact schema, metric unit/scope/denominator semantics, and duplicate identities. Complete identity is the tuple `model`, `reasoning_effort`, `harness`, `config`. Identical duplicates warn and deterministically use the first source row; conflicting duplicates warn in legacy mode and block strict compare/rank. `rank --strict-rank` or `--strict-duplicates` blocks conflicting duplicate rows while preserving raw rows in output.

`diagnose` is the offline shape/provenance/diagnostics route: it NEVER fetches or exposes row/task content. Successful scopes advertise `dependencies: []` and `independence_class: "unknown"` unless explicit source-observed claims exist; NEVER infer overlap score adjustment.

## Cache and release authority

Cache bytes are immutable SHA-256-addressed artifacts. Redacted sidecars/manifests contain source URL, concrete version, validators, parser identity, hash, and raw-byte reference. Legacy version-addressed files remain readable and MAY be promoted non-destructively; promotion NEVER deletes or rewrites the caller’s legacy file. Refresh failure is an error unless `--allow-stale` is explicit. `--snapshot` is an explicit historical local read preserving stale/historical provenance.

`latest` means only configured `DEEPSWE_DEFAULT_VERSION`, otherwise code default `v1.1`; no manifest/homepage/directory release discovery. A source manifest is authoritative only when explicitly configured and its exact version/path/hash agreement validates. NEVER guess releases or mix versions. Every operational error is one compact JSON object on stdout; human diagnostics belong on stderr. NEVER fetch or emit task, exercise, release, trajectory, or trial-artifact content.
