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
- Current evaluation pages publish an initial model subset and a public catalog manifest. Live `evaluation` follows the same-origin HTTPS manifest and decodes the frontend's AES-GCM/gzip format to retrieve the full catalog.
- `coverage: manifest_models` identifies catalog retrieval. `population_source` records its URL, retrieval time, and SHA-256 separately from the page.
- Saved HTML replay never fetches. A page containing a manifest but only initial rows reports `coverage: initial_models_only`; do not present it as the full population.
- Legacy embedded score rows remain supported. Generic extraction cannot guarantee every future page layout.
- Preserve unknown fields. Field preservation does not establish units or benchmark semantics.
- If no recognizable rows exist, report an extraction error. If a manifest fails, do not silently fall back to initial rows.
- Select published metric paths explicitly. Current examples are `terminalbenchV40`, `automationBenchPartialScore`, and `automationBenchBreakdown.strictScore`. The last is full-workflow success; `completion` is a different measure.
- Missing metrics remain missing even when their model exists in the catalog. A requested sort with no comparable values fails rather than returning an unsorted list as a ranking.

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
