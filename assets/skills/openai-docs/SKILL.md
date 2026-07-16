---
name: openai-docs
description: Use current official OpenAI and Codex docs through MCPorter for APIs, models, configuration, and citations.
---

# OpenAI Docs

Use the configured MCPorter server `openai-docs` for current official OpenAI documentation. It is public: do not authenticate. Use fetched documentation as evidence; do not invent undocumented behavior.

If `mcporter` is not on `PATH`, replace the leading `mcporter` in each command below with `nix run github:numtide/llm-agents.nix#mcporter --`.

## Discover and call

The live server schema is authoritative. Run discovery only when the available tools are unknown or may have changed:

```text
mcporter list openai-docs --brief
```

Inspect only the tool needed when an argument or output shape matters:

```text
mcporter list openai-docs.<tool> --schema
```

Use these live tools:

```text
mcporter call openai-docs.search_openai_docs query='responses api tools'
mcporter call openai-docs.fetch_openai_doc url='https://developers.openai.com/...'
mcporter call openai-docs.list_openai_docs
mcporter call openai-docs.list_api_endpoints
mcporter call openai-docs.get_openapi_spec url='https://developers.openai.com/...'
```

Use `--args '<JSON object>'` for optional, array, or multiline arguments. Do not maintain static schemas.

## Routes

### Documentation

1. Search with a compact 2–6-term query: `search_openai_docs`.
2. Fetch the best returned URL with `fetch_openai_doc`; pass `anchor` only for a known needed section.
3. Answer from that narrow page or section and cite it. Narrow and repeat search before broadening.

Use `list_openai_docs` only to browse when there is no clear query. If this public MCP route is unavailable or unhelpful, search or fetch only official OpenAI domains and cite the page.

### API reference

For endpoint discovery, call `list_api_endpoints`. For API schema, required fields, or parameter details, call `get_openapi_spec` for the relevant API URL and pair it with the relevant guide/reference fetch. Inspect that tool's live schema first when optional output controls matter.

### Models and Codex

For latest/current/default model selection, first fetch `https://developers.openai.com/api/docs/guides/latest-model.md`. An explicit model target wins; do not silently migrate it.

For an unspecified latest/current/default migration or prompt upgrade, run the cross-platform resolver before applying guidance:

```text
node <skill-dir>/scripts/resolve-latest-model-info.cjs
```

Require `model`, `migrationGuideUrl`, and `promptingGuideUrl`, then fetch the returned guide URLs through `fetch_openai_doc`.

For broad Codex self-knowledge, run the existing helper in a writable session, then read only relevant sections from its emitted outline and manual:

```text
node <skill-dir>/scripts/fetch-codex-manual.mjs
```

If it cannot run or lacks the needed current fact, use the documentation route above. Keep uncertainty bounded when official sources do not establish a claim.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Latest-model fallback | `references/latest-model.md` | The live latest-model page is unavailable |
| Upgrade fallback | `references/upgrade-guide.md` | Live migration guidance is unavailable |
| Prompting fallback | `references/prompting-guide.md` | Live prompting guidance is unavailable |
| GPT-5.6-family migration | `references/upgrading-to-gpt-5p6-sol.md` | The requested migration targets that family |
