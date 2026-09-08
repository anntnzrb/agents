# Artificial Analysis evaluation pages

Use for dedicated benchmark pages, not provider matrix or composite capability indexes.

## Source routing
Provider endpoint speed, latency, price: `/leaderboards/providers`; `fetch`, then `query`.
Published model benchmark metrics (intelligence, coding, agentic, math): official models API; `fetch`, then `query`.
Dedicated benchmark leaderboard: `/evaluations/<slug>`; `evaluation <url>`.
Dedicated evaluation pages remain separate from official model snapshot metrics.
Evaluator input: public HTML/Next.js Flight payload, or saved HTML/RSC via `--input` for reproducible extraction without another network request.

## Generic command

```text
uv run --script <skill-dir>/scripts/cli.py evaluation \
  https://artificialanalysis.ai/evaluations/<benchmark-slug> \
  --sort-by score --order desc --limit 25 \
  --output-json <temp-dir>/evaluation.json
```

Saved response:

```text
uv run --script <skill-dir>/scripts/cli.py evaluation \
  --input <temp-dir>/evaluation.html
```

Returns source metadata, frame/row counts, applied filters, and rows. Page-copied rows: `value_status=published`; sorting, limiting, and later arithmetic: derived.

## Extraction
- Parse Next.js `self.__next_f.push(...)` payloads and standard colon-delimited RSC frames.
- Select the largest list containing recognizable model identity and numeric score fields.
- Generic evaluation extraction is schema-dependent and does not guarantee parsing every benchmark page layout or frontend revision.
- Preserve unknown fields; NEVER reduce a dedicated page to a fixed benchmark-specific schema.
- Use `--input` for cached or saved source when a result must be replayed deterministically.
- If no recognizable rows exist, report an extraction error; NEVER guess a nested list.

## Comparability
- Dedicated benchmark scores remain separate from official model snapshot metrics (`intelligence`, `coding`, `agentic`).
- Retain benchmark version, task count, repeats, test harness, sandbox, and score definition with rows whenever exposed by source. Do not assume fixed benchmark versions across runs.
- Preserve cost and token scope: API evaluation spend, subscription quota, per-task cost, and per-attempt cost are distinct quantities.
- Page-total divided by task-count is derived, even when both inputs are published.
- NEVER average scores across benchmark populations into one quality number without explicit normalization and workload definition.

## Evidence and comparison gates
Dedicated rows retain `value_status: "published"` for copied page values; sorting, limiting, arithmetic, and derived classifications remain derived.
When available, additive metric evidence records raw/normalized values, unit, source path/field, parser/version, artifact hash, semantics, and comparison eligibility.
Missing, placeholder, malformed, non-finite, unknown-semantics, unit-mismatched, or mixed-scope values remain visible but blocked.

Lossless JSON/source artifact: authority for unknown fields. Markdown/TSV exports: fixed named-column views.
NEVER merge dedicated scores with official model snapshot quality metrics merely because model labels match.
Record only source-published release/population evidence; otherwise release/population `null` and emit a `requirements_claim` overlap note.

## URL and artifact safety
Public URL input: HTTPS-only; query credentials redacted.
Use `--input <file>` for deterministic local HTML/RSC replay; mark `freshness.mode: "snapshot"`/historical, not live.
Source bytes: SHA-256 content-addressed with immutable manifests. NEVER persist authorization/cookie headers or raw dotenv values.
