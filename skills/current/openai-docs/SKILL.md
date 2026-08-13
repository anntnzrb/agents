---
name: openai-docs
description: Use current official OpenAI and Codex docs through MCPorter for APIs, models, configuration, and citations.
license: AGPL-3.0-or-later
---

# OpenAI Docs

- MUST use MCPorter `openai-docs` for official documentation
- Public server: NEVER authenticate
- MUST ground answers in fetched documentation
- NEVER invent undocumented behavior

Missing `mcporter`: MUST use this Nix prefix:

```text
nix run github:numtide/llm-agents.nix#mcporter --
```

## Discover and call

- Live server schema MUST remain authoritative
- MUST discover live inventory first:

```text
mcporter list openai-docs --brief
```

Argument constraints: MUST inspect only targeted live schema:

```text
mcporter list openai-docs.<tool> --schema
```

- Output fields: MUST inspect actual results
- Tool declarations MAY omit output schemas

Use these live tools:

```text
mcporter call openai-docs.search_openai_docs query='responses api tools'
mcporter call openai-docs.fetch_openai_doc url='https://developers.openai.com/...'
mcporter call openai-docs.list_openai_docs
mcporter call openai-docs.list_api_endpoints
mcporter call openai-docs.get_openapi_spec url='https://developers.openai.com/...'
```

Complex arguments SHOULD use `--args '<JSON object>'`.

## Routes

### Documentation

1. Compact query (2–6 terms): MUST use `search_openai_docs`
2. MUST fetch the best URL; `anchor` requires a known section
3. MUST cite the narrow source before broadening search

- Clear query absent: MAY browse with `list_openai_docs`
- MCP unavailable/unhelpful: MUST use official OpenAI domains
- MUST cite the fetched page

### API reference

- Endpoint discovery MUST use `list_api_endpoints`
- Endpoint schemas MUST use `get_openapi_spec`
- MUST pair schemas with relevant guides or references
- Optional output controls: MUST inspect targeted live schema first

### API troubleshooting

- You MUST first distinguish pre-response DNS, TLS, or network failures from API responses
- You MUST classify `401` from the actual error payload and headers as authentication
- You MUST classify `403` from the actual error payload and headers as project, model, or permission access
- For `429`, you MUST use the actual error payload and headers to distinguish `insufficient_quota` from rate limiting
- You MUST use current official documentation via the documentation route for remediation
- NEVER guess about configuration errors or blindly retry them

### Models and Codex

- Latest/current/default model: MUST fetch `https://developers.openai.com/api/docs/guides/latest-model.md` first
- Explicit model targets MUST win. NEVER migrate silently

Unspecified migration or prompt upgrade: MUST run the resolver:

```text
uv run --script <skill-dir>/scripts/cli.py latest-model
```

- Resolver output MUST include all three fields:
  `model`, `migrationGuideUrl`, `promptingGuideUrl`.
- MUST fetch returned guides through `fetch_openai_doc`

Broad Codex self-knowledge: MUST run the helper in a writable session:

```text
uv run --script <skill-dir>/scripts/cli.py codex-manual
```

- MUST read only relevant outline/manual sections
- Helper unavailable/insufficient: MUST use the documentation route
- Official evidence absent: MUST state bounded uncertainty

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Dated broad tool inventory or exact-schema fallback | `references/tool-schema-snapshot.md` | ONLY for broad tool comparison, or when live discovery fails; NEVER before a targeted live schema |
| Latest-model fallback | `references/latest-model.md` | The live latest-model page is unavailable |
| Upgrade fallback | `references/upgrade-guide.md` | Live migration guidance is unavailable |
| Prompting fallback | `references/prompting-guide.md` | Live prompting guidance is unavailable |
| GPT-5.6-family migration | `references/upgrading-to-gpt-5p6-sol.md` | The requested migration targets that family |
