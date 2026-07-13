---
name: notebooklm
description: Query NotebookLM notebooks and knowledge bases through the nlm CLI.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# NotebookLM CLI

Use `nlm` to list notebooks, select a target, and ask questions via `generate-chat` or `chat`.

## Workflow

1. Verify CLI
   - `command -v nlm` (if missing, ask how they want to install)

2. Verify auth
   - Do not rely on parent-shell env alone; auth may live in `~/.nlm/env`, CLI/browser state, or env vars `NLM_AUTH_TOKEN`, `NLM_COOKIES`
   - Tracked template: `.env.example` (usable as a local template or for `~/.nlm/env`)
   - Prove auth with a real command such as `nlm list`, not just an env inspection
   - If missing, run:
     - `nlm auth --all --notebooks`
     - If profiles are locked: `NLM_USE_ORIGINAL_PROFILE=1 nlm auth --all --notebooks --debug`
   - If auth still fails, **fail fast** and ask the user to complete browser login manually

3. Select notebook
   - `nlm list` (shows recent)
   - Ask user to pick an ID if not provided

4. Interact
   - Headless single question: `nlm generate-chat <notebook-id> "<prompt>"`
   - Interactive session: `nlm chat <notebook-id>`
   - Source-based transformations: ask for source IDs, then use `summarize`, `explain`, `outline`, `faq`, `briefing-doc`, `timeline`, `toc`

5. Guardrails
   - Always confirm before destructive operations: `rm`, `rm-source`, `rm-note`, `delete-artifact`, `audio-rm`
   - Confirm before privacy-impacting actions: `share` (public) and `share-private`

## Quick commands

```bash
nlm list
nlm generate-chat <notebook-id> "Question about my knowledge base"
nlm chat <notebook-id>
```

## Environment

- Tracked template: `.env.example`
- Common vars:
  - `NLM_AUTH_TOKEN`
  - `NLM_COOKIES`
  - `NLM_BROWSER_PROFILE`
  - `NLM_USE_ORIGINAL_PROFILE=1`
- If you already use `~/.nlm/env`, keep that as the active auth file; the template is mainly a portable key list.

## Notes

- If user says "talk to my knowledge base", ask which notebook ID to use
- No implicit state: do not assume a last-used notebook
