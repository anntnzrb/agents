# AGENTS.md

annt owns this.

## Important Locations
- My repos: `~/repos/`
- My LLM agents configs: `~/.config/agents/` (SSOT)

## Protocol
- Bugs: add regression test when it fits
- Keep files <~500 LOC; modularize/split/refactor as needed
- Web: search early; quote exact errors; prefer 2024..2026 sources
- Style: telegraph; noun-phrases: ok. Drop filler/grammar, min tokens
- Avoid calling `python`/`python3` - use `uv` to interface python
- For GitHub related stuff use `gh`
- Use research tools for web search, library/API documentation, code generation, setup/config steps, etc

## Flow
- Use tmux only for interactive/persistent
- Prioritize subagents/parallism to maximize throughput; only avoid if user explicitly asks not to delegate
- Before handoff: run full gate

## Critical Thinking
- Fix root cause (not band-aid)
- Unsure: read more code; if still stuck, ask w/ short options
- Conflicts: call out; pick safer path
- Unrecognized changes: assume other agent; keep going; focus your changes. If it causes issues, stop + ask user

## Tools

### Research
When code, repo, web searches or user opinions (any kind of external exploration) are requested, load the research skill.

### tmux
- Use only when you need persistence/interaction
- Quick refs: `tmux new -d -s agent-shell`, `tmux attach -t agent-shell`, `tmux list-sessions`, `tmux kill-session -t agent-shell`

### Navigation / Refactoring / Exploring
#### AST Grep
- Load skill: `ast-grep` for fast, read-only structural code search during repo exploration
