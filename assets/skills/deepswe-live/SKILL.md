---
name: deepswe-live
description: Analyze published DeepSWE benchmark metrics and model-efficiency results with deterministic versioned JSON data.
license: GPL-3.0-or-later
compatibility: Requires uv; network is needed only for fetch.
metadata:
  author: anntnzrb

---

# deepswe-live

Use this skill when the user asks for DeepSWE benchmark scores, model-efficiency comparisons, confidence intervals, trial summaries, or a reproducible metrics report. Keep every answer metrics/results-only: do not fetch or discuss task/exercise/release/trial-artifact content.

## Non-negotiable rules

- Run the CLI before answering current-data questions; do not substitute remembered values
- Treat stdout as one compact JSON object. Read diagnostics only from stderr; never parse logs as results
- `scope.value_status` distinguishes `published`, `published_raw`, and `derived`; never present a derived number as a published score
- Resolve `latest` through the one configured default (`DEEPSWE_DEFAULT_VERSION`, otherwise the code default `v1.1`). Accept explicit semantic versions `v1.1+`; reject major-only versions and never fetch legacy `v1`
- Use only the artifact endpoints documented in `references/provenance.md`. Do not guess versions from a homepage or mix versions
- A network, HTTP, malformed, schema, or mixed-version failure is an error. Do not silently use a last-good cache. Use `--allow-stale` or an explicit `--snapshot` when stale local data is intentional

## Entry point

```text
uv run --script <skill-dir>/scripts/cli.py <command> [options]
```

Use `fetch` to acquire the published leaderboard (and opt-in raw trials with `--trials`), then use `report` for the primary model-efficiency decision. Use `--snapshot <path>` for a historical local artifact. No command downloads task/exercise/release/trial-artifact records.

## Fast routing

- Current model-efficiency report: `report` (fetch first when freshness matters)
- Published leaderboard ordering: `rank` with an explicit metric and order
- Published aggregate inspection: `stats` or `schema`
- Included raw-trial metrics: `trials` with explicit filter overrides when needed
- Compare two snapshots: `compare`; both snapshots MUST use the same benchmark version
- Acquire artifacts: `fetch`; `--trials` is opt-in because the raw file is large

The CLI returns `ok`, `schema_version`, `command`, and either `data` or `error`. Check `ok` before reading any result. `data.scope` and `data.provenance` are required on successful metrics responses.

## Analysis guardrails

- Published leaderboard rows are authoritative; never re-aggregate them
- Preserve config identity as `model + reasoning_effort + harness + config`; never merge tiers or configurations
- Keep raw extrema separate from recommendations. Recommendations have no quality/sample exclusion by default; apply `--min-attempted`, `--min-tasks`, or `--min-pass-at-1` only when the user requests a threshold
- Every ranked row carries available attempted/task counts, score/pass fields, `ci_lo`, `ci_hi`, `ci_half`, and derived `ci_width = ci_hi - ci_lo`. “Confidence” means CI width, not a probability of correctness
- Pareto defaults to maximize `pass_at_1` and minimize `mean_output_tokens`, `mean_cost_usd`, and `mean_agent_steps`; `report --pareto-axis metric:order` enables an explicit alternate frontier without inventing a composite score
- `report --efficiency name=numerator/denominator` adds a derived ratio; zero denominators and missing/non-finite inputs stay null with a reason

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Command choice, version/cache behavior | `references/command-routing.md` | Before selecting a command or handling a fetch/cache result |
| JSON envelope and metric fields | `references/output-contract.md` | Before consuming output or writing a report |
| URLs, freshness, validators, and labels | `references/provenance.md` | Before citing data or describing published/raw/derived values |
| Provenance, same-version refreshes, or new releases | `references/release-maintenance.md` | When upstream reruns models, publishes v1.12/v2.0, or the default release must move |
| Complete flags and examples | `README.md` | When fast routing does not answer the invocation question |

## Hardened evidence and comparison controls

The existing v1 envelope and raw row fields remain authoritative. Hardened
responses add evidence under `metrics` (or the row's `derived` object):

- `raw_value` and `normalized_value` (null when unavailable);
- `unit`, `normalization`, `source_path`, `parser`, `parser_version`, and
  artifact hash/raw-byte reference when available;
- `value_status`: `published`, `published_raw`, or `derived`;
- `metric_semantics_status` and `comparison_eligibility` (`eligible` or
  `blocked`), with explicit `blocked_reasons`.

Missing, placeholder, malformed, non-finite, out-of-range, unknown, or
ambiguous values stay visible and are never silently converted to zero.
Derived confidence-interval width and efficiency values never overwrite
published fields.

Use `--strict-semantics` to block values without known metric semantics.
`compare --strict-compare` additionally proves compatible artifact schema,
metric unit/scope/denominator semantics, and duplicate identities. Complete
identity is the four-field tuple `model`, `reasoning_effort`, `harness`,
`config`; identical duplicates warn and use the first source row
deterministically, while conflicting duplicates warn in legacy mode and block
strict compare/rank. Use `rank --strict-rank` (or `--strict-duplicates`) to
block conflicting duplicate rows while preserving those raw rows in output.

`diagnose` is the offline shape/provenance/diagnostics route. It never fetches
and does not expose row or task content. Successful scopes also advertise
`dependencies: []` and `independence_class: "unknown"` unless explicit
source-observed claims exist; no overlap score adjustment is inferred.

## Cache and release authority

Cache bytes are immutable SHA-256-addressed artifacts with redacted sidecars
and manifests containing source URL, concrete version, validators, parser
identity, hash, and raw-byte reference. Legacy version-addressed files remain
readable and may be promoted non-destructively; promotion never deletes or
rewrites the caller's legacy file. A refresh failure is an error unless
`--allow-stale` is explicit. `--snapshot` is an explicit historical local
read and preserves stale/historical provenance.

`latest` means only the configured `DEEPSWE_DEFAULT_VERSION`, or code default
`v1.1`; there is no manifest/homepage/directory release discovery. A source
manifest is authoritative only if explicitly configured and its exact
version/path/hash agreement validates. Never guess a release or mix versions.
Every operational error is one compact JSON object on stdout; human
diagnostics belong on stderr. Keep this skill metrics/results-only: never
fetch or emit task, exercise, release, trajectory, or trial-artifact content.
