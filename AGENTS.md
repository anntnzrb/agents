# AGENTS.md

jag owns this. init once: greet + 1 motivating line.

## Protocol
- Bugs: add regression test when it fits
- Keep files <~500 LOC; split/refactor as needed
- Web: search early; quote exact errors; prefer 2024–2025 sources
- Style: telegraph; noun-phrases: ok. Drop filler/grammar. Min tokens (global AGENTS + replies)
- Avoid calling `python`/`python3` - use `uv` to interface python
- For GitHub related stuff use `gh`
- Always use Context7 MCP for library/API documentation, code generation, setup/config steps, explicitly asking by me

## Important Locations
- My repos: `~/repos/`
- My LLM agents configs: `~/.config/agents/`

## Flow
- Use Codex background for long jobs; tmux only for interactive/persistent (debugger/server)
- Prioritize subagents to maximize throughput; only avoid if user explicitly asks not to delegate
- Signals: research, tests, docs, review, parallel workstreams

## Build / Test
- Before handoff: run full gate

## Git
- Commits: Conventional Commits styled; no amend unless asked
- Safe by default: `git status/diff/log`. Push only when user asks
- Don’t delete/rename unexpected stuff; stop + ask
- No repo-wide S/R scripts; keep edits small/reviewable
- Avoid manual `git stash`; if Git auto-stashes during pull/rebase, that’s fine (hint, not hard guardrail)
- Big review: `git --no-pager diff --color=never`
- Multi-agent: check `git status/diff` before edits; ship small commits

## Critical Thinking
- Fix root cause (not band-aid)
- Unsure: read more code; if still stuck, ask w/ short options
- Conflicts: call out; pick safer path
- Unrecognized changes: assume other agent; keep going; focus your changes. If it causes issues, stop + ask user

## Tools

### gh
- GitHub CLI for PRs/CI/releases. Given issue/PR URL (or `/pull/5`): use `gh`, not web search
- Examples: `gh issue view <url> --comments -R owner/repo`, `gh pr view <url> --comments --files -R owner/repo`

### tmux
- Use only when you need persistence/interaction (debugger/server)
- Quick refs: `tmux new -d -s agent-shell`, `tmux attach -t agent-shell`, `tmux list-sessions`, `tmux kill-session -t agent-shell`

### Brave & Exa Skills
- Use these for web searching and resource gathering

### ast-grep
- Load the ast-grep skill for fast, read-only structural code search during repo exploration.
