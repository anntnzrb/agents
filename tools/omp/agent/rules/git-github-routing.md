---
name: git-github-routing
description: Prefer GitHub/read tools for GitHub-relevant git and gh commands
condition:
  - '\bgh\s+(?:(?:issue|pr)\s+(?:view|list|status|diff|checks|checkout|create)|search\s+(?:issues|prs|repos|code|commits)|run\s+(?:watch|view)|repo\s+view)\b'
  - '\bgit\s+(?:ls-remote\s+https://github\.com/|fetch\s+\S+\s+(?:pull/\d+/|refs/pull/))\b'
scope:
  - text
  - thinking
  - tool:bash
interruptMode: never
---
For GitHub issue/PR content, use `read("issue://N")`, `read("pr://N")`, or `read("pr://N/diff")`. For PR checkout, GitHub search, repo view, Actions watch, PR creation, or PR push, use the `github` tool. Plain local `git status`, `git diff`, `git log`, `git show`, branch inspection, remote URL checks, and non-GitHub remotes MAY stay in `bash`. NEVER comment or mutate GitHub state unless the user explicitly asks.
