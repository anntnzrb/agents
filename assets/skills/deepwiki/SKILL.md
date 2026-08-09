---
name: deepwiki
description: Query public GitHub repository documentation and codebase questions through the configured DeepWiki MCP server.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

---

# DeepWiki

Use MCPorter `deepwiki` for public GitHub repository docs and codebase Q&A.
- NEVER assume native DeepWiki tools are mounted
- MUST run from the agent-config root
- MUST pass `--config assets/mcporter.jsonc`
- Missing `mcporter`: MUST use the Nix fallback

```text
nix run github:numtide/llm-agents.nix#mcporter --
```

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Fallback contracts or broad tool/schema comparison | `references/tools-schema.md` | MUST read only after live discovery fails or broad comparison needs exact contracts |

## Workflow

1. MUST discover the live inventory first:

   ```text
   mcporter --config assets/mcporter.jsonc list deepwiki --brief
   ```

2. MUST inspect the selected tool's live schema:

   ```text
   mcporter --config assets/mcporter.jsonc list deepwiki.<tool> --schema
   ```

3. Live success MUST override the snapshot
   - NEVER infer absent response fields
   - NEVER load snapshots except for broad comparison
4. Live failure MUST label snapshot use as fallback
5. Matching inventory uses these routing rules:
   - Repositories MUST use `owner/repo`
   - `ask_question` accepts one or up to 10 repositories
   - Other tools accept exactly one repository
   - Broad exploration SHOULD inspect structure before contents
   - Narrow questions SHOULD use `ask_question`
   - Multi-repository calls MUST use exact `--args` JSON
6. Insufficient DeepWiki MAY switch to public-web research; MUST disclose

`read_wiki_contents` can be large; MUST narrow first unless full docs are needed.
