# Artificial Analysis evaluation pages

Use this guide for dedicated benchmark pages at `/evaluations/<slug>`.

## Source routing

Query provider endpoint speed, latency, and price by running `fetch` on `/leaderboards/providers`, then running `query`.

Query published model benchmark metrics (`intelligence`, `coding`, `agentic`, `math`) from the official models API by running `fetch`, then running `query`.

Query dedicated benchmark leaderboards at `/evaluations/<slug>` with `evaluation <url>`.

Dedicated evaluation pages remain separate from official model snapshot metrics.

Evaluator input accepts public HTML or Next.js Flight payloads, or saved HTML/RSC files via `--input` for reproducible local extraction without network requests.

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

This command returns source metadata, frame and row counts, applied filters, and rows. Rows copied directly from the page set `value_status: "published"`. Sorted, limited, and calculated values set `value_status: "derived"`.

## Extraction

- Parse Next.js `self.__next_f.push(...)` payloads and standard colon-delimited RSC frames.
- Current evaluation pages publish an initial model subset and a public catalog manifest. Live `evaluation` runs follow the same-origin HTTPS manifest and decode the frontend AES-GCM/gzip payload to retrieve the full catalog.
- Set `coverage: manifest_models` when catalog retrieval succeeds. Record the manifest URL, retrieval timestamp, and SHA-256 hash in `population_source` separately from the page payload.
- Replaying saved HTML never makes network requests. A saved page containing a manifest but only initial rows reports `coverage: initial_models_only`. Present this accurately as a partial subset rather than the full population.
- Legacy embedded score rows remain supported. Generic extraction cannot guarantee unannounced future page layouts.
- Preserve unknown fields in the output payload. Field preservation does not establish units or benchmark semantics.
- If no recognizable rows exist, raise an extraction error. If manifest decoding fails, raise an error; do not silently fall back to initial rows.
- Select published metric paths explicitly. Supported examples include `terminalbenchV40`, `automationBenchPartialScore`, and `automationBenchBreakdown.strictScore`. The `automationBenchBreakdown.strictScore` metric measures full workflow success, whereas `completion` measures partial attempt progress.
- Keep missing metrics recorded as missing even when their model appears in the catalog. Fail sorting requests when values are missing or incomparable instead of returning an unsorted list as a ranking.

## Comparability

- Keep dedicated benchmark scores separate from official model snapshot metrics (`intelligence`, `coding`, `agentic`).
- Retain the benchmark version, task count, repeat count, test harness, sandbox configuration, and score definition with rows whenever the source exposes them. Benchmark versions change across evaluation runs.
- Preserve cost and token scopes separately. API evaluation spend, subscription quotas, per-task costs, and per-attempt costs represent distinct quantities.
- Mark calculated values such as total cost divided by task count as derived, even when both inputs come directly from published fields.
- NEVER average scores across benchmark populations into a single composite quality score without explicit normalization and defined workloads.

## Evidence and comparison gates

Rows copied directly from the page retain `value_status: "published"`. Sorting, limiting, arithmetic operations, and derived classifications remain `value_status: "derived"`.

When available, additive metric evidence records raw and normalized values, units, source path, source field, parser version, artifact hash, semantics, and comparison eligibility.

Retain missing, placeholder, malformed, non-finite, unit-mismatched, mixed-scope, or unverified semantic values in the output, but block them from comparison operations.

Lossless JSON source artifacts serve as the authoritative reference for unknown fields. Markdown and TSV exports provide fixed column views.

NEVER merge dedicated benchmark scores with official model snapshot quality metrics based solely on matching model labels.

Record only verified published release and population evidence from the source. Set release and population fields to `null` and attach a `requirements_claim` overlap note when evidence is absent.

## URL and artifact safety

Public URL inputs require HTTPS. Redact query credentials before sending requests.

Pass `--input <file>` for deterministic local HTML or RSC replay. Set `freshness.mode: "snapshot"` for historical files.

Store source bytes using SHA-256 content addressing with immutable manifests. NEVER persist authorization headers, cookie headers, or raw environment file values.
