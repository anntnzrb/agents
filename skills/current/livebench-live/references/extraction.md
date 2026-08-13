# Extraction

## Representation precedence
Stop at first usable, validated representation:
1. official JSON asset
2. official CSV/tabular asset
3. HTML-embedded `application/json`
4. RSC/Next-style frame
5. JSON-LD
6. semantic HTML table
7. serialized data attributes
8. plain text (diagnostic fallback only)

## Provenance and promotion
Each selected document retains artifact ID, source URL, extraction method, parser/version, source paths, raw fields, and SHA-256 evidence. A candidate MUST establish identity/release; a number alone does not promote it.

## LiveBench shell and unavailable sources
LiveBench shell: empty root; JavaScript-required `noscript`. Static parsing MUST NOT fabricate chart values. If no official bundle or data asset is discoverable, return `REQUIRES_RENDERED_SOURCE` or `SOURCE_UNAVAILABLE`, including attempted URLs. No browser or external JavaScript runtime dependency.

## Parsing
CSV strict requirements: header; coherent row objects; `model` identity column for release score/cost tables. Malformed rows → structured errors or partial diagnostics.

Category JSON: map raw display labels → ordered task-key arrays.

Retain and diagnose unknown columns and unmapped task keys; NEVER drop them.
