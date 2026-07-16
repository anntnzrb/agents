---
name: deepwiki
description: Query public GitHub repository documentation and codebase questions through the configured DeepWiki MCP server.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# DeepWiki

Use the configured MCPorter `deepwiki` server for public GitHub repository documentation and targeted codebase Q&A. Do not assume native DeepWiki tools are mounted.

If `mcporter` is not on PATH, replace the leading `mcporter` in each command below with `nix run github:numtide/llm-agents.nix#mcporter --`.
## Workflow

1. Start with `mcporter list deepwiki --brief` only when available tools are unknown or may have changed.
2. Require `repoName=owner/repo`.
3. Map an unfamiliar repository with `mcporter call deepwiki.read_wiki_structure repoName=facebook/react`; fetch contents only after narrowing: `mcporter call deepwiki.read_wiki_contents repoName=facebook/react`.
4. Ask narrow questions with `mcporter call deepwiki.ask_question repoName=facebook/react question='Where is concurrent rendering implemented?'`; inspect only its schema with `mcporter list deepwiki.ask_question --schema` when argument details matter.
5. If DeepWiki is insufficient, use an appropriate public-web research source and say so.

`read_wiki_contents` can be large; do not fetch it before narrowing the topic.
