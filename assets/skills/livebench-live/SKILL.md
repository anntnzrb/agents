---
name: livebench-live
description: Query official LiveBench releases, dynamic categories, subtasks, model rows, scores, and published costs.
---

# LiveBench Live

Use this skill when a request names LiveBench, a LiveBench release/category/subtask, Coding or Agentic Coding, objective benchmark comparisons, or cost per successful task. The skill reads official application/bundle release state and exact release-scoped table/category/cost assets; repository, Hugging Face, and paper data are separate historical surfaces and are never silently substituted.

## Entrypoint

```text
uv run --script assets/skills/livebench-live/scripts/cli.py <command> [options]
```

Commands: `releases`, `catalog`, `leaderboard`, `model`, `compare`, `category`, `subtasks`, `catalog-diff`, `diagnose`, `schema`, plus practical `refresh` and `snapshot`.

## Fast routing

- Resolve `latest` on every live request; output the concrete source release ID and date.
- Use `--release <id>` for an advertised release. An unadvertised release requires exact caller-supplied official `--table-url`, `--categories-url`, and optional `--cost-url`; directory enumeration and guessed filenames are forbidden.
- Use `--snapshot <path>` only for an explicit historical fixture/manifest. It is `historical:true`, `stale:false`; failed refreshes are errors unless `--allow-stale` is explicit.
- Use `--cache-dir <path>` to select an immutable content-addressed cache. ETag and Last-Modified are sent on revalidation; raw bytes are referenced by manifests, never embedded in normal output.
- If the app shell has no permitted official bundle/assets, return `REQUIRES_RENDERED_SOURCE`; this implementation has no browser or external JavaScript runtime dependency.

## Output guardrails

Every invocation emits exactly one compact JSON object on stdout, including failures. Errors contain `ok:false`, `schema_version:"1"`, `command`, and a structured `error`; operational text belongs on stderr. Successful metric responses include `scope`, `rows`, `warnings`, `provenance`, and a nearest-scope `value_status` (`published`, `derived`, `missing`, or `unparsed`). `null` means unavailable, never zero.

Score-table subtask cells remain `published`. Category means and overall are separate `derived` values with formulas and input paths; overall is **not** an automatically inferred pass metric. Published `cost_per_question` and `cost_per_successful_task` remain separate from any selected-scope cost derivation. Unknown models, columns, categories, fields, and metrics remain visible; unknown semantics are comparison-blocked. Provider is null unless explicitly published.

## Required follow-up reads

| Need | Read | When |
| Output envelope | `references/output-contract.md` | Before consuming stdout or designing integrations |
| Source/release authority | `references/source-discovery.md` | Before live release/catalog requests or interpreting bundle limitations |
| Asset extraction | `references/extraction.md` | When shell, bundle, CSV, JSON, embedded JSON, RSC, or HTML fallback is involved |
| Dynamic records and formulas | `references/normalization.md` | Before score/category/subtask/cost comparisons |
| Cache and evidence | `references/provenance.md` | Before refresh, stale, snapshot, or provenance questions |
| Drift and failures | `references/drift-handling.md` | On missing/malformed/mixed-release/unknown-field diagnostics |
| Overlap warnings | `references/overlap-model.md` | When comparing coding populations across benchmarks |
| Deterministic validation | `references/eval-notes.md` | Before fixture/eval or opt-in live-smoke work |

Never infer a fixed release/category/model allow-list from examples. Do not use screenshots, OCR, search snippets, list prices, Artificial Analysis, or DeepSWE values as LiveBench numeric evidence.
