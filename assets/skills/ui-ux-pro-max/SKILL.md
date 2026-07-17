---
name: ui-ux-pro-max
description: "Design, build, review, or improve web/mobile UI and UX: layout, accessibility, styles, and components."
---

# UI/UX Pro Max

Design, build, or review user-facing web/mobile interfaces with searchable
style, color, typography, product, UX, chart, and stack guidance.

## Trigger

Use for UI structure, visual design, components, interaction, accessibility,
responsive behavior, animation, design systems, or interface quality. Skip pure
backend, data, infrastructure, and non-visual work.

## Entry point

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

MUST use the bundled CLI; MUST NOT invoke internal Python files directly.

## Workflow

1. Inspect the product type, audience, desired tone, platform, and project stack.
2. Start with a design-system search:

   ```text
   uv run --script <skill-dir>/scripts/cli.py "<product> <industry> <tone>" --design-system -p "<project>"
   ```

3. Add `--domain <domain>` for targeted evidence or `--stack <stack>` for
   implementation guidance. Use `--variance`, `--motion`, and `--density` only
   with `--design-system`.
4. Add `--persist` only when the user wants `design-system/MASTER.md`; add
   `--page <name>` for an override.
5. Implement the smallest coherent system, then verify accessibility, touch,
   responsive layout, performance, contrast, reduced motion, and error states.

## Core constraints

- MUST preserve visible focus, keyboard access, semantic labels, and zoom.
- MUST NOT use color alone for meaning or emoji as structural icons.
- MUST meet WCAG contrast and platform touch-target minimums.
- MUST reserve async/media space, avoid horizontal overflow, and respect
  `prefers-reduced-motion`.
- SHOULD use one icon family, semantic tokens, a consistent spacing/type scale,
  and one primary action per screen.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Full rules, domain map, examples, and delivery checklists | `references/design-guide.md` | Broad design/review work or a rule needs detail |
| Live searchable design data | `data/*.csv`, `data/stacks/*.csv` via CLI | CLI search only; MUST NOT load all CSVs into context |
| Internal search/generation behavior | `scripts/search.py`, `scripts/core.py`, `scripts/design_system.py` | Debugging the bundled CLI |
