---
name: apple-shortcuts
description: Build, inspect, debug, validate, sign, and remix Apple Shortcuts and Shortcuts.app automations.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Apple Shortcuts

Produce a deterministic action graph first. Produce an importable artifact only when the user asks to create, modify, export, or sign a shortcut file. This keeps routine automation help human-reviewable and avoids generating brittle XML for a problem that only needs ordered Shortcuts.app actions.

## Route the request

| Request | Route |
| --- | --- |
| What existing shortcuts do; run history; Smart Prompt permissions | `inspect` first. Keep redaction on unless the user explicitly requests raw data. |
| Build or explain a normal shortcut | Produce a blueprint and ordered action graph. Do not default to plist/XML. |
| Create, remix, validate, or import a `.shortcut` | Blueprint → XML → validate → sign → confirm the signed file exists. |
| A shortcut fails | Reproduce minimally, validate its file, inspect types/wiring, then permissions and app/network state. |
| App integration | Use App Intents/App Shortcuts guidance; distinguish app-supplied actions from user-level workflows. |

## Core workflow

1. Scope goal, devices, trigger, inputs, outputs, side effects, privacy constraints, and target OS.
2. For normal workflows, create a blueprint before listing exact actions. Use explicit variable names and control-flow branches.
3. For an artifact request, write the smallest complete XML plist. Never invent an action identifier, parameter key, enum value, UUID, or variable reference.
4. Validate the XML before signing. Treat a validator pass as structural evidence, not proof that app permissions, third-party actions, or network calls will work.
5. Sign only after validation and only when the user requested an importable `.shortcut`. Preserve the unsigned XML and archive it.
6. Finish with happy-path, empty-input, denied-permission, and device-specific checks.

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
uv run --script "$SKILL_DIR/scripts/validate_shortcut.py" /path/to/Shortcut.xml
bash "$SKILL_DIR/scripts/sign_shortcut.sh" /path/to/Shortcut.xml \
  --name "Shortcut Name" --output-dir /path/to/output
```

`sign_shortcut.sh` needs macOS and the built-in `shortcuts` CLI. It archives the XML, retries Apple signing after binary-plist conversion when needed, and emits the archive/signed paths as JSON. `--output-dir` is required: it never writes to an implicit location.

## Artifact rules

- Use `uuidgen | tr '[:lower:]' '[:upper:]'` for each action UUID. Never use placeholder or repeated UUIDs.
- Start with the smallest working workflow. Validate, then polish icon/color/comments.
- Prefer first-party actions and explicit inputs. Treat third-party actions, automation triggers, and OS-gated fields as compatibility risks.
- Validate against the intended target only. Set `SHORTCUTS_PLAYGROUND_TARGET_MACOS=27` or `SHORTCUTS_PLAYGROUND_TARGET_PLATFORM=ios` only for deliberate target-specific work.
- Do not enable a post-write hook by default. A hook runs code on every matching file write; it belongs in a separately audited, explicitly trusted Codex plugin—not this portable skill.

## Local inspection and documentation

Inspecting installed shortcuts reads the local Shortcuts database and can report library metadata, run events, and Smart Prompt permissions. Keep its default redaction enabled; `--no-redact` requires explicit user authorization.

Use the optional local documentation corpus when it is present. It is supplementary, not a prerequisite for validation:

```bash
uv run --script "$SKILL_DIR/scripts/cli.py" search \
  --query "ask for input action" --group support --top 10
```

See `references/corpus-usage.md` only when corpus search is needed; see `references/plist-authoring.md` for XML structure, `references/debug-playbook.md` for failures, and `references/developer-integration.md` for App Intents.

## Output contract

For normal shortcut work, provide: `Goal`, `Target Devices`, `Trigger`, `Action Graph`, `Variables`, `Failure Handling`, `Validation Matrix`, and `Notes`.

For explicit file work, replace `Action Graph` with `Shortcut File Structure` and include the validation command, signing command, output path, and import/test steps.

## Constraints

- Do not claim an artifact is complete before validation passes and the signed file exists with non-zero size.
- Do not expose local secrets found during inspection.
- Do not use raw plist/XML as the default response format.
- Do not fetch web documentation for routine use; prefer the bundled validator, local corpus when available, and Apple-provided CLI behavior.
