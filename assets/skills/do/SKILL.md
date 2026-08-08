---
name: do
description: Delegate a task to a subagent when the user says /do or asks for delegation.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Do Skill

Delegate the task to a subagent to preserve parent context. Execute autonomously.

Optional arguments: $ARGUMENTS

## Rules

- Return only the result; no reasoning process, intermediate steps, or tool outputs
- Concise, actionable answer for the parent agent
- Batch independent tool calls in parallel
