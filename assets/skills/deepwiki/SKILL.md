---
name: deepwiki
description: Query GitHub repository documentation and codebase Q&A through DeepWiki MCP.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# DeepWiki MCP

Use DeepWiki MCP for public GitHub repo documentation and Q&A.

## Constraints

- Public repos only (private needs Devin account)
- `repoName` must be `owner/repo`

## Suggested flow

1. `read_wiki_structure` for topic map
2. `read_wiki_contents` for scoped docs
3. `ask_question` for targeted Q&A  
   If empty/insufficient: fall back to Exa/Brave.

## Notes

- `read_wiki_contents` can be large; use `ask_question` for narrow answers

## Quick start

```bash
read_wiki_structure repoName="owner/repo"
```

## Common calls

```bash
read_wiki_contents repoName="owner/repo"
ask_question repoName="owner/repo" question="..."
```

## Query templates

See `assets/query-templates.json` for reusable parameter templates.

## Reference

See `reference.md` for server URL details, tool catalog, and defaults.
