---
name: exa-search
description: Primary search: deep web research, structured answers, and content retrieval using Exa. Use for heavy research, multi-step synthesis, or rich structured outputs. Load the mcporter skill to execute this skill’s MCP calls.
---

# Exa MCP

Use Exa for web search, code context, crawling, and research tasks. This skill documents Exa’s MCP surface and tool parameters.

## Quick start

```bash
web_search_exa query="..." numResults=5
```

## Common calls

```bash
get_code_context_exa query="..." tokensNum=5000
crawling_exa url="https://example.com" maxCharacters=3000
company_research_exa companyName="Exa AI" numResults=3
deep_researcher_start instructions="..." model="exa-research"
deep_researcher_check taskId="..."
```

Poll `deep_researcher_check` until `status` is `completed`.

## Query templates

See `assets/query-templates.json` for reusable parameter templates.

## Reference

See `reference.md` for server URL details, tool catalog, and defaults.
