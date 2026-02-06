# Delegation Policy

- Delegate-first: if task is not a trivial single-file needle query, spawn subagent(s) early.
- Prefer dedicated delegation tools (`task`, `spawn_agent`, etc) when available; otherwise use equivalent agent orchestration.
- For open-ended discovery, use explorer/research subagents before manual local search.
- Parallelize independent workstreams in one batch/message whenever possible.
- For 3+ subtasks, split by scope/ownership and synthesize results centrally.
- While subagents run, orchestrate (wait/send follow-ups); avoid duplicating their active work.
- Use specialized agents/skills whenever scope matches; avoid generic agent fallback by default.
- Skip delegation only if user explicitly forbids it, tooling is unavailable, or task is truly tiny.
