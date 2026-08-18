---
name: notebooklm
description: "Use when the user asks to query a NotebookLM notebook or knowledge base through the nlm CLI."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# NotebookLM CLI

`nlm`: list/select notebooks; question them with `generate-chat` or `chat`.

## Workflow

1. **CLI** — Verify with `command -v nlm`; if absent, ask how user wants to install it.
2. **Auth**
   - Do not rely on parent-shell environment alone. Auth may be in `~/.nlm/env`, CLI/browser state, `NLM_AUTH_TOKEN`, or `NLM_COOKIES`.
   - `.env.example`: tracked template for local use or `~/.nlm/env`.
   - Prove auth with a real command, e.g. `nlm list`, not environment inspection alone.
   - If auth is missing, run `nlm auth --all --notebooks`.
   - If profiles are locked: `NLM_USE_ORIGINAL_PROFILE=1 nlm auth --all --notebooks --debug`.
   - If auth still fails, fail fast; ask user to complete browser login manually.
3. **Notebook** — Run `nlm list` (recent notebooks); if no ID supplied, ask user to choose one.
4. **Interact**
   - Single headless question: `nlm generate-chat <notebook-id> "<prompt>"`.
   - Interactive: `nlm chat <notebook-id>`.
   - Transform sources: ask for source IDs, then use `summarize`, `explain`, `outline`, `faq`, `briefing-doc`, `timeline`, or `toc`.
5. **Confirmations** — Always confirm before destructive operations: `rm`, `rm-source`, `rm-note`, `delete-artifact`, `audio-rm`. Confirm before privacy-impacting actions: `share` (public) and `share-private`.

## Quick commands

```bash
nlm list
nlm generate-chat <notebook-id> "Question about my knowledge base"
nlm chat <notebook-id>
```

## Environment

- Tracked template: `.env.example`.
- Common vars: `NLM_AUTH_TOKEN`, `NLM_COOKIES`, `NLM_BROWSER_PROFILE`, `NLM_USE_ORIGINAL_PROFILE=1`.
- If `~/.nlm/env` is already used, keep it as the active auth file; template is mainly a portable key list.

## Notes

- “Talk to my knowledge base” → ask which notebook ID.
- No implicit state: never assume a last-used notebook.

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|Full command and authentication reference|`reference.md`|Before nontrivial CLI use or troubleshooting|
|Basic notebook operations|`cookbook/basics.md`|Listing, creating, renaming, or deleting notebooks|
|Chat workflows|`cookbook/chat.md`|Asking questions or managing chat sessions|
|Source operations|`cookbook/sources.md`|Adding, listing, or removing sources|
|Source transformations|`cookbook/transformations.md`|Summaries, outlines, FAQs, timelines, or TOCs|
|Media workflows|`cookbook/media.md`|Audio or media operations|
|Artifact workflows|`cookbook/artifacts.md`|Creating, inspecting, or deleting artifacts|
