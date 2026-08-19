---
name: deepwiki
description: "Use when a public GitHub repository question needs DeepWiki documentation or codebase evidence."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# DeepWiki

Use MCPorter `deepwiki` for public GitHub repository docs and codebase Q&A.
- NEVER assume native DeepWiki tools are mounted
- MUST pass `--config ~/.mcporter/mcporter.json` (the generated MCPorter configuration)
- Missing `mcporter`: MUST use the Nix fallback

```text
nix run github:numtide/llm-agents.nix#mcporter --
```

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|Fallback contracts or broad tool/schema comparison|`references/tools-schema.md`|MUST read only after a call/schema failure or broad comparison needs exact contracts|

## Workflow

1. Select one of the three known tools and call it directly; do not list the server or inspect schemas first:

   ```text
   mcporter --config ~/.mcporter/mcporter.json call deepwiki.ask_question --args '{"repoName":"owner/repo","question":"<question>"}'
   mcporter --config ~/.mcporter/mcporter.json call deepwiki.read_wiki_structure repoName=owner/repo
   mcporter --config ~/.mcporter/mcporter.json call deepwiki.read_wiki_contents repoName=owner/repo
   ```

2. If a call reports a missing tool or invalid input, inspect only that tool's live schema, correct the call, and retry once:

   ```text
   mcporter --config ~/.mcporter/mcporter.json list deepwiki.<tool> --schema
   ```

3. Live success MUST override snapshot; NEVER infer absent response fields.
4. Live failure MUST label snapshot use as fallback.
5. Routing:
   - Repositories MUST use `owner/repo`.
   - `ask_question` accepts one or up to 10 repositories.
   - Other tools accept exactly one repository.
   - Broad exploration SHOULD inspect structure before contents.
   - Narrow questions SHOULD use `ask_question`.
   - Multi-repository calls MUST use exact `--args` JSON.
6. Insufficient DeepWiki MAY switch to public-web research; MUST disclose.

`read_wiki_contents` can be large; MUST narrow first unless full docs are needed.
