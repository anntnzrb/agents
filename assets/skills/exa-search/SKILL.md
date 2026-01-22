---
name: exa-search
description: Deep web research, structured answers, and content retrieval using Exa. Use for heavy research, multi-step synthesis, or rich structured outputs; optionally pair with brave-search for fast scoping but not required. Execute Exa MCP calls via MCPorter (load the mcporter skill).
---

# Exa MCP

Use Exa for web search, code context, crawling, and research tasks. This skill documents Exa’s MCP surface; execute calls via MCPorter (see the mcporter skill for CLI mechanics).

## Quick start

```bash
mcporter list exa
mcporter call exa.web_search_exa query="..." numResults=5 --output json
```

## Common calls

```bash
mcporter call exa.get_code_context_exa query="..." tokensNum=5000 --output json
mcporter call exa.crawling_exa url="https://example.com" maxCharacters=3000 --output json
mcporter call exa.company_research_exa companyName="Exa AI" numResults=3 --output json
mcporter call exa.deep_researcher_start instructions="..." model="exa-research" --output json
mcporter call exa.deep_researcher_check taskId="..." --output json
```

Poll `deep_researcher_check` until `status` is `completed`.

## Query templates

See `assets/query-templates.json` for reusable parameter templates.

## Reference

See `reference.md` for server URL details, tool catalog, and defaults.
