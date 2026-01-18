---
description: Delegate task to subagent (preserves parent context)
subtask: true
---

$ARGUMENTS

RULES:

- Execute autonomously, return ONLY the result
- No reasoning process, intermediate steps, or tool outputs
- Concise, actionable answer for the parent agent
- Batch independent tool calls in parallel
