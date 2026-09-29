---
name: verification-skill
description: "Use to create or audit a project-local verify-APP skill that drives the real app and captures proof."
license: AGPL-3.0-or-later
---

# Verification Skill

A verification skill is a project-local skill that lets an agent launch the real app, drive it the way a user does, and capture evidence. It is the loop that lets an agent prove its own work instead of waiting for a human to check it. This skill generates one and keeps it honest.

Ported from pstack `create-verification-skill` and `maintain-verification-skill` (Lauren Tan, MIT). See [NOTICE.md](NOTICE.md).

## Pick a mode

| Mode | Use when | Read |
| --- | --- | --- |
| `create` | The project has no scripted way to prove UI, CLI, or service behavior | [references/create.md](references/create.md) |
| `maintain` | A `verify-<app>` skill exists and the app has changed, or the user asks to audit it | [references/maintain.md](references/maintain.md) |

Read the mode file in full before acting. Applying a mode from this table alone is not allowed.

## Where the generated skill lives

- Write the skill to `<repo>/.agents/skills/verify-<app>/`. Codex, pi, and omp discover project skills there.
- Claude Code discovers project skills in `.claude/skills/`. Link it instead of copying: `ln -s ../../.agents/skills/verify-<app> .claude/skills/verify-<app>`. One copy per harness drifts.
- The generated skill belongs to the app repository. Never put it in the shared skills SSOT.
- Helper scripts use the app's own stack and toolchain. The shared-skill `scripts/cli.py` rule does not apply to them.

## Non-negotiables

- A generated skill that was never executed end to end is a draft, not a deliverable.
- Evidence survives every cleanup. Confirm it at its named location after teardown.
- Drive only instances this run started. Never kill by process name.
- Never edit product code in `maintain` mode. A broken behavior is a product gap to report, not doc drift to paper over.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Generation steps and required sections | [references/create.md](references/create.md) | `create` mode |
| Audit pass and outcomes | [references/maintain.md](references/maintain.md) | `maintain` mode |
| Feature map shape | [references/feature-map-example/README.md](references/feature-map-example/README.md) | Seeding or auditing a feature map |
