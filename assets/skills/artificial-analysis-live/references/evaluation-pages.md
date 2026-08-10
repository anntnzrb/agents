# Artificial Analysis evaluation pages

Read this when a user asks about a dedicated benchmark page rather than the provider matrix or a composite capability index.

## Source routing

| Need | Source | Use |
| --- | --- | --- |
| Provider endpoint speed, latency, and price | `/leaderboards/providers` | `fetch`, then `query` |
| Composite coding capability and token composition | `/models/capabilities/coding` | `coding` |
| Dedicated benchmark leaderboard | `/evaluations/<slug>` | `evaluation <url>` |
| Coding-agent composite | `/agents/coding-agents` | Treat as a separate benchmark; do not merge with Coding Index |

The dedicated evaluator reads the public HTML/Next.js Flight payload. It can also read a saved HTML/RSC response with `--input`, which makes extraction reproducible without another network request.

## Generic command

```text
uv run --script <skill-dir>/scripts/cli.py evaluation \
  https://artificialanalysis.ai/evaluations/terminalbench-v2-1 \
  --sort-by score --order desc --limit 25 \
  --output-json <temp-dir>/terminalbench.json
```

For a saved response:

```text
uv run --script <skill-dir>/scripts/cli.py evaluation \
  --input <temp-dir>/evaluation.html
```

The command returns source metadata, frame/row counts, applied filters, and rows. Rows are copied from the page and marked `value_status=published`; sorting, limiting, and any later arithmetic are derived operations.

## Extraction rules

- Parse Next.js `self.__next_f.push(...)` payloads and standard colon-delimited RSC frames
- Select the largest list containing recognizable model identity and numeric score fields
- Preserve unknown fields; do not reduce a dedicated page to a fixed benchmark-specific schema
- Use `--input` for a cached source when a page changes frequently or a result must be replayed
- If no recognizable rows are found, report the extraction error; do not guess a nested list

## Comparability guardrails

- A dedicated benchmark score is not automatically the Coding Index or Coding Agent Index
- Keep benchmark version, task count, repeats, harness, sandbox, and score definition with the rows whenever the source exposes them
- Costs and token counts must retain their scope: API evaluation spend, subscription quota, per-task cost, and per-attempt cost are different quantities
- A value derived by dividing a page total by a task count is derived, even when both inputs are published
- Do not average scores from different benchmark populations into one quality number without an explicit normalization and workload definition


## Evidence and comparison gates

Dedicated rows keep `value_status: "published"` for copied page values, while
sorting, limiting, arithmetic, and derived classifications remain derived.
When available, additive metric evidence records raw/normalized values, unit,
source path/field, parser/version, artifact hash, semantics, and comparison
eligibility. Missing, placeholder, malformed, non-finite, unknown-semantics,
unit-mismatched, or mixed-scope values remain visible but blocked.

Keep the lossless JSON/source artifact as the authority for unknown fields;
Markdown/TSV exports are fixed named-column views. Do not merge a dedicated
score with Coding Index, Coding Agent Index, or provider quality rows merely
because model labels match. Record only source-published release/population
evidence; otherwise leave release/population null and emit a
`requirements_claim` overlap note.

## URL and artifact safety

Public URL input is HTTPS-only and query credentials are redacted. Use
`--input <file>` for deterministic local HTML/RSC replay; it is marked
`freshness.mode: "snapshot"`/historical rather than live. Source bytes are
content-addressed with SHA-256 and immutable manifests; authorization/cookie
headers and raw dotenv values are never persisted.