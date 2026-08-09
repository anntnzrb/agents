# Extraction

Extraction stops at the first usable validated representation in this order:

1. official JSON asset;
2. official CSV/tabular asset;
3. embedded `application/json` in HTML;
4. RSC/Next-style frame;
5. JSON-LD;
6. semantic HTML table;
7. serialized data attributes;
8. plain text as a last diagnostic fallback.

Each selected document retains artifact ID, source URL, extraction method, parser/version, source paths, raw fields, and SHA-256 evidence. A candidate that cannot establish identity/release is not promoted merely because it contains a number.

The current LiveBench shell has an empty root and a JavaScript-required `noscript`; static parsing does not fabricate chart values. If no official bundle or data asset can be discovered, return `REQUIRES_RENDERED_SOURCE` (or `SOURCE_UNAVAILABLE`) with attempted URLs. This skill intentionally has no browser or external JavaScript runtime dependency.

CSV parsing is strict: a header is required, row objects must be coherent, a `model` identity column is required for release score/cost tables, and malformed rows become structured errors or partial diagnostics. Category JSON is a map of raw display labels to ordered task-key arrays. Unknown columns and unmapped task keys are retained and diagnosed rather than dropped.
