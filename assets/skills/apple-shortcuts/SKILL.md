---
name: apple-shortcuts
description: "Design, implement, debug, and optimize Apple Shortcuts automations across iPhone, iPad, Mac, Apple Watch, and Apple Vision Pro. Use when requests involve building shortcut logic, selecting actions/variables, creating personal or home automations, managing installed shortcuts from the Mac CLI, generating importable .shortcut/plist files, integrating App Intents/App Shortcuts, troubleshooting shortcut behavior, or mining the local shortcuts-docs-corpus for authoritative references."
---

# Apple Shortcuts

## Activation Triggers
- "create a shortcut", "build a shortcut", "shortcut automation", "Siri shortcut".
- Device-specific shortcut requests for iPhone, iPad, Mac, Apple Watch, Apple Vision Pro.
- Requests to list, open, inspect, or run installed shortcuts from the Mac CLI.
- Requests for `.shortcut` files, shortcut plists, signing/import flow, or raw action serialization.
- Requests mentioning Shortcuts actions, variables, dictionaries, menus, repeat/if flow, URL schemes, x-callback-url.
- Requests mentioning App Intents, App Shortcuts, SiriKit donation, or WWDC shortcut integration guidance.
- Requests to debug a failing shortcut or optimize shortcut reliability/performance.

## Core Workflow
1. Scope the automation: goal, device(s), trigger type, input/output, side effects, and privacy constraints.
2. Choose implementation path:
   - User-level shortcut only: use support-guide patterns.
   - App integration: use App Intents/App Shortcuts docs.
   - CLI/local execution: include `shortcuts` command behavior and output handling.
   - Raw `.shortcut` authoring: use only when the user explicitly wants plist/XML output, a signable artifact, or low-level action wiring.
3. If user asks "what do my current shortcuts do?", run local introspection workflow before guessing.
4. If user wants to open or run an installed shortcut on Mac, inventory first, then choose UI handoff or CLI execution.
5. Build a shortcut blueprint before listing actions unless the request is explicitly for raw plist output.
6. Translate blueprint into an action graph with explicit variable names and control flow.
7. If using raw `.shortcut` authoring, keep the output minimal and use `references/plist-authoring.md` for wiring/signing details.
8. Add a validation matrix (happy path, empty input, denied permissions, network/API failures, device-specific differences).
9. Provide final deliverable:
   - Shortcut build plan (ordered actions + parameter values).
   - Raw plist/signing steps when the request is explicitly for an importable file.
   - Trigger/automation setup instructions.
   - Test checklist and rollback/safety notes.

## Quick Commands
Run these from the skill directory (`apple-shortcuts/`) so relative `scripts/...` paths resolve.

- Search corpus for authoritative snippets:
```bash
uv run scripts/search_expert_chunks.py \
  --query "run shortcut from command line output type" --top 8
```
- Filter search to official support docs:
```bash
uv run scripts/search_expert_chunks.py \
  --query "ask for input action" --group support --top 10
```
- Generate a structured shortcut blueprint:
```bash
uv run scripts/make_blueprint.py \
  --goal "capture meeting notes and send summary" \
  --devices "iPhone,Mac" \
  --trigger "Share Sheet" \
  --inputs "shared text" \
  --outputs "markdown note, copied summary" \
  --automation-type "manual"
```
- Enumerate installed shortcuts with IDs/folders:
```bash
shortcuts list --show-identifiers
shortcuts list --folders
```
- Open a shortcut in Shortcuts.app for manual inspection/editing:
```bash
shortcuts view "My Shortcut"
```
- Run an installed shortcut:
```bash
shortcuts run "My Shortcut"
shortcuts run "My Shortcut" --input-path ./input.txt
printf '%s\n' "hello world" | shortcuts run "My Shortcut"
```
- Decode local action graphs (safe redaction on by default):
```bash
uv run scripts/inspect_local_shortcuts.py --visible-only --include-folders
```
- Deep inspect one shortcut with run history + smart prompt permissions:
```bash
uv run scripts/inspect_local_shortcuts.py \
  --name "LLM" \
  --include-run-stats \
  --include-smart-prompts
```
- Raw export (use only when explicitly needed; includes sensitive data unless redaction remains enabled):
```bash
uv run scripts/inspect_local_shortcuts.py --json --raw
uv run scripts/inspect_local_shortcuts.py --json --raw --no-redact
```
- Sign a generated `.shortcut` file for import:
```bash
shortcuts sign --mode anyone --input MyShortcut.shortcut --output MyShortcut_signed.shortcut
```

## Local Introspection Protocol
1. Inventory first: `shortcuts list --show-identifiers` and folder listing.
2. Decode shortcut internals from `~/Library/Shortcuts/Shortcuts.sqlite` using `inspect_local_shortcuts.py` (not `shortcuts view`, which only opens UI).
3. Include `--include-run-stats` to report usage/outcome telemetry from `ZSHORTCUTRUNEVENT`.
4. Include `--include-smart-prompts` to report permission grants from `ZSMARTPROMPTPERMISSION` (destination app + mode/status).
5. Note hidden entries (e.g. placeholders/templates) and filter with `--visible-only` when user wants only normal library items.
6. Keep redaction enabled by default; only use `--no-redact` when user explicitly asks for raw secrets.

## Mac CLI Operations
- Use `shortcuts view "<name>"` only when the user explicitly wants to open/edit the shortcut in Shortcuts.app.
- Use `shortcuts run "<name>"` for direct execution, `--input-path` for file input, and stdin piping for text input.
- If `shortcuts run/view` fails with `The shortcut "Name" could not be found.`, re-run inventory first, then retry with exact casing and spacing.
- For machine-readable automation output, pair execution with explicit CLI output flags when available; see `references/debug-playbook.md`.

## Output Contract
- Always produce named sections:
  - `Goal`
  - `Target Devices`
  - `Trigger`
  - `Action Graph`
  - `Variables`
  - `Failure Handling`
  - `Validation Matrix`
  - `Notes`
- In `Action Graph`, list ordered actions with exact action names when known.
- Keep user-facing steps deterministic and executable.
- Call out assumptions explicitly.
- When the user explicitly requests a raw `.shortcut` artifact, replace `Action Graph` with `Shortcut File Structure` and include signing/import steps.

## Device-Specific Rules
- iPhone/iPad:
  - Prefer Shortcuts User Guide iOS pages for action behavior.
  - For automation triggers, separate personal vs home automation pathways.
- Mac:
  - Include command-line compatibility if user asks about local workflows.
  - Prefer `inspect_local_shortcuts.py` for analysis; reserve `shortcuts view` for UI handoff.
  - Note differences between widget/app trigger surfaces and iOS trigger surfaces.
- Apple Watch:
  - Distinguish "run from watch" vs "create/edit from phone/mac".
- Vision Pro:
  - Use visionOS shortcut pages for user interaction constraints and shortcut entry points.
- Developer/App Intents:
  - Use App Intents + App Shortcuts docs; include phrase discoverability and Spotlight/Shortcuts surfaces.

## Troubleshooting Protocol
1. Reproduce with minimal shortcut.
2. Isolate failing action by binary split.
3. Inspect input types entering each branch.
4. Validate permissions, app availability, and network state.
5. Replace brittle app-specific actions with neutral primitives when possible.
6. Re-test on each target device class.

## Corpus and References
- Start with `references/corpus-usage.md` to locate and query `shortcuts-docs-corpus`.
- Use `references/workflows.md` for implementation flow and output structure.
- Use `references/pattern-cookbook.md` for action-level patterns.
- Use `references/debug-playbook.md` for failure diagnosis.
- Use `references/developer-integration.md` for App Intents and WWDC sources.
- Use `references/plist-authoring.md` only for explicit raw `.shortcut`/plist authoring requests.

## Constraints
- Use local corpus only. Do not fetch documentation from the web.
- Prefer official Apple docs over community sources for normative behavior.
- Treat community sources as pattern inspiration; mark them non-authoritative.
- Do not invent action names; if uncertain, say uncertain and provide nearest known action.
- For local shortcut inventory/decoding tasks, prefer `scripts/inspect_local_shortcuts.py` over manual plist/sqlite shell pipelines.
- Do not default to raw plist/XML output when a blueprint or action graph answers the request.
