# Extraction precedence

Extraction is ordered and evidence-backed:

1. official JSON API or JSON asset;
2. official CSV/tabular asset;
3. embedded HTML JSON (`application/json`, Astro island props, `__NEXT_DATA__`);
4. Next/RSC-style frames;
5. JSON-LD;
6. semantic HTML tables;
7. data attributes/serialized state;
8. plain text as a last resort.

The selected method, source URL, path, parser/version, raw value and artifact hash remain attached to each field. Plain text never overrides a usable structured representation.

## Astro props

Decode HTML entities and Astro tagged wrappers recursively. Search the decoded tree for selector/version/detail islands rather than relying on volatile island names or hashed asset filenames. `benchmarkView.metadata` and `benchmarkView.default.metadata` (and corresponding task paths) are separate candidates. Equal candidates may be used with both paths recorded; conflicting candidates produce `SCHEMA_DRIFT` and `PARTIAL_EXTRACTION`, preserve all values, and never use last-write-wins.

## HTML tables and RSC

Table lookup is header-based, not positional. RSC frames are decoded independently of frame order and unrelated frames are ignored. A new header/field survives under `raw_fields`; missing mappings remain visible with a diagnostic.

## Delivery failures

A page containing only a JavaScript shell, `#root`, or noscript JavaScript-required message is not an empty successful table. Return `REQUIRES_RENDERED_SOURCE`; a status/auth failure returns `SOURCE_UNAVAILABLE` or `SOURCE_AUTH_REQUIRED`. No chart or screenshot is numeric evidence.
