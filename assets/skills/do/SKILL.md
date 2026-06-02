---
name: do
description: Delegate a task to a subagent and return only the result. Activate when user says /do or asks to delegate work.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Do Skill

Delegate the task to a subagent to preserve parent context. Execute autonomously.

Optional arguments: $ARGUMENTS

## Rules

- Return only the result; no reasoning process, intermediate steps, or tool outputs
- Concise, actionable answer for the parent agent
- Batch independent tool calls in parallel
