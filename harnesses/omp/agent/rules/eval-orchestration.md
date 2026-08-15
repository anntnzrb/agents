---
name: eval-orchestration
description: Prefer eval for scripts, parsing, JSON, transcripts, and batch analysis
condition:
  - '\b(JSON|jsonl|session|transcript|analy[sz]e|aggregate|count|batch|parse|rewrite config|filesystem|data munging|multi-step script|script)\b'
  - '\b(?:python|node|bun)\s+-[ce]\b|\bjq\b|\bawk\b|\bwhile\b|\bfor\s+\w+\s+in\b|<<[A-Za-z_]'
scope:
  - text
  - thinking
  - tool:bash
interruptMode: never
---
Use `eval` for orchestration, JSON/JSONL/session/transcript analysis, filesystem batch work, deterministic config rewrites, and multi-step scripts. Use the managed eval environment; missing imports are handled by the `eval-packages` recovery rule. Avoid heredocs, shell loops, inline interpreter snippets, raw pip/pip3, and quote-heavy Bash when `eval` can run the logic directly.
