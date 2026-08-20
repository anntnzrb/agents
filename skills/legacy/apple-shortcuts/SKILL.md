---
name: apple-shortcuts
description: "Use when Apple Shortcuts, Shortcuts.app, .shortcut files, signing, automation, or debugging are involved."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Apple Shortcuts

Deterministic action graph first. For routine automation help, keep workflows human-reviewable; produce an importable artifact only for user-requested shortcut-file creation, modification, export, or signing, avoiding brittle XML when ordered Shortcuts.app actions suffice.

## Route requests

- Existing shortcuts, run history, or Smart Prompt permissions → `inspect` first; keep redaction on unless user explicitly requests raw data.
- Build/explain normal shortcut → blueprint + ordered action graph; do not default to plist/XML.
- Create, remix, validate, or import `.shortcut` → blueprint → XML → validate → sign → confirm signed file exists.
- Shortcut failure → minimal reproduction → file validation → type/wiring inspection → permissions and app/network state.
- App integration → App Intents/App Shortcuts guidance; distinguish app-supplied actions from user-level workflows.

## Workflow

1. Scope goal, devices, trigger, inputs, outputs, side effects, privacy constraints, and target OS.
2. Normal workflow: blueprint before exact actions; name variables explicitly and show control-flow branches.
3. Artifact: write smallest complete XML plist; NEVER invent action identifiers, parameter keys, enum values, UUIDs, or variable references.
4. Validate XML before signing. Validator pass is structural evidence, not proof that permissions, third-party actions, or network calls work.
5. Sign only after validation and only for a requested importable `.shortcut`; preserve and archive unsigned XML.
6. Check happy path, empty input, denied permission, and device-specific behavior.

## Commands

Set `SKILL_DIR` to this skill directory. Use explicit commands; do not rely on executable bits or shell sourcing.

```bash
# Inventory and privacy-safe local inspection
shortcuts list --show-identifiers
shortcuts list --folders
uv run --script "$SKILL_DIR/scripts/cli.py" inspect --visible-only --include-folders
uv run --script "$SKILL_DIR/scripts/cli.py" inspect --name "My Shortcut" --include-run-stats --include-smart-prompts

# Blueprint a user-level shortcut
uv run --script "$SKILL_DIR/scripts/cli.py" blueprint \
  --goal "capture meeting notes and send a summary" \
  --devices "iPhone,Mac" --trigger "Share Sheet" \
  --inputs "shared text" --outputs "markdown note, copied summary" \
  --automation-type "manual"

# Validate and sign an explicitly requested artifact
uv run --script "$SKILL_DIR/scripts/cli.py" validate <shortcut.xml>
uv run --script "$SKILL_DIR/scripts/cli.py" sign <shortcut.xml> \
  --name "Shortcut Name" --output-dir /path/to/output
```

`sign` requires macOS and the built-in `shortcuts` CLI; archives XML, retries Apple signing after binary-plist conversion when needed, and emits archive/signed paths as JSON. `--output-dir` is required and never implicit.

## Artifact rules

- Generate each action UUID with `uuidgen | tr '[:lower:]' '[:upper:]'`; NEVER use placeholders or repeated UUIDs.
- Start with smallest working workflow; validate before polishing icon, color, or comments.
- Prefer first-party actions and explicit inputs; third-party actions, automation triggers, and OS-gated fields are compatibility risks.
- Validate only against intended target. Set `SHORTCUTS_PLAYGROUND_TARGET_MACOS=27` or `SHORTCUTS_PLAYGROUND_TARGET_PLATFORM=ios` only for deliberate target-specific work.
- NEVER enable a post-write hook by default: it runs code on every matching file write and belongs in a separately audited, explicitly trusted Codex plugin, not this portable skill.

## Local inspection and documentation

Installed-shortcut inspection reads the local Shortcuts database and may report library metadata, run events, and Smart Prompt permissions. Keep default redaction; `--no-redact` requires explicit user authorization.

Use optional local documentation corpus when present; it is supplementary, not required for validation:

```bash
uv run --script "$SKILL_DIR/scripts/cli.py" search \
  --query "ask for input action" --group support --top 10
```

## Required follow-up reads

- Corpus lookup → `references/corpus-usage.md`, only when corpus search is needed.
- Artifact XML/plist structure → `references/plist-authoring.md`, before authoring an importable artifact.
- Failure diagnosis → `references/debug-playbook.md`, when validation, signing, permissions, or runtime behavior fails.
- App Intents/App Shortcuts → `references/developer-integration.md`, for app-supplied actions or developer integration.
- Reusable blueprint patterns → `references/pattern-cookbook.md`, when the action graph needs input/control-flow patterns.
- Route variants → `references/workflows.md`, when choosing user-level, artifact, inspection, or developer workflows.

## Output contract

For normal shortcut work, provide: `Goal`, `Target Devices`, `Trigger`, `Action Graph`, `Variables`, `Failure Handling`, `Validation Matrix`, `Notes`.

Explicit file work replaces `Action Graph` with `Shortcut File Structure` and includes validation command, signing command, output path, and import/test steps.

## Constraints

- NEVER claim an artifact complete until validation passes and the signed file exists with non-zero size.
- NEVER expose local secrets found during inspection.
- NEVER use raw plist/XML as default response format.
- NEVER fetch web documentation for routine use; prefer bundled validator, local corpus when available, and Apple-provided CLI behavior.
