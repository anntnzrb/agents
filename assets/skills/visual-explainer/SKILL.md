---
name: visual-explainer
description: Generate beautiful, self-contained HTML pages that visually explain systems, code changes, plans, and data. Use when the user asks for a diagram, architecture overview, diff review, plan review, project recap, comparison table, or any visual explanation of technical concepts. Also use proactively when you are about to render a complex ASCII table (4+ rows or 3+ columns) — present it as a styled HTML page instead.
license: GPL-3.0-or-later
compatibility: Requires a browser to view generated HTML files. Optional surf-cli for AI image generation.
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Visual Explainer

Generate self-contained HTML pages that visually explain systems, code changes, plans, data, and prose. ALWAYS open the result in a browser. NEVER render ASCII art or ASCII tables when this skill is loaded.

<critical>
- Entry point MUST be:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

- Set `<skill-dir>` to this skill directory. NEVER rely on shell sourcing, executable bits, or shebang dispatch.
- Proactive table rule: when you would present structured tabular data as an ASCII box-drawing table, generate an HTML page instead if it has 4+ rows or 3+ columns. This includes comparisons, audits, feature matrices, status reports, requirement checks, config matrices, test summaries, dependency lists, permission tables, and endpoint inventories. NEVER wait for the user to ask. You MAY include a brief chat summary; the table itself MUST be HTML.
- Output every page to `~/.agent/diagrams/`, open it in the browser, and tell the user the exact file path.
- Every page MUST support both themes using `prefers-color-scheme` and MUST respect `prefers-reduced-motion`.
  </critical>

## Available Commands

Detailed prompt templates live in `./commands/`. In Pi, use slash commands (`/diff-review`). In Claude Code, use namespaced commands (`/visual-explainer:diff-review`). In Codex, use `/prompts:diff-review` if installed to `~/.codex/prompts/`, or invoke `$visual-explainer` and describe the workflow.

| Command                | What it does                                                    |
| ---------------------- | --------------------------------------------------------------- |
| `generate-web-diagram` | Generate an HTML diagram for any topic                          |
| `generate-visual-plan` | Generate a visual implementation plan for a feature             |
| `generate-slides`      | Generate a magazine-quality slide deck                          |
| `diff-review`          | Visual diff review with architecture comparison and code review |
| `plan-review`          | Compare a plan against the codebase with risk assessment        |
| `project-recap`        | Mental model snapshot for context-switching back to a project   |
| `fact-check`           | Verify accuracy of a document against actual code               |
| `share`                | Deploy an HTML page to Vercel and get a live URL                |

<workflow>
## Core Workflow

1. Choose a direction before writing HTML. NEVER default to generic dark-blue technical styling.
2. Determine audience and density: developer system model, PM overview, team proposal review, data audit, prose explanation, or slide presentation.
3. Treat visual structure as default. Essays, READMEs, articles, and docs become cards, diagrams, grids, timelines, callouts, or tables; prose blocks are accents, not the page mode.
4. Read the template/reference routed by content type before generating. Load only what applies.
5. Write one self-contained `.html` file. External assets are limited to CDN links for fonts and optional libraries.
6. Open the file in a browser and inspect it from the user's perspective before responding.
   </workflow>

## Routing Table

| Need                                                                                     | Load                                                                                                                                                            | Use                                                                                                                   |
| ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Text-heavy architecture overviews                                                        | `./templates/architecture.html`                                                                                                                                 | CSS Grid cards + flow arrows when descriptions, code refs, tool lists, or rich card content matter more than topology |
| Flowcharts, sequence diagrams, ER, state machines, mind maps, class diagrams, C4         | `./templates/mermaid-flowchart.html`, `./references/mermaid-rules.md`                                                                                           | Mermaid when automatic edge routing or specialized syntax materially improves comprehension                           |
| Complex architecture with 15+ elements                                                   | `./templates/mermaid-flowchart.html`, `./references/mermaid-rules.md`, `./references/css-patterns.md`                                                           | Hybrid: simple Mermaid overview plus detailed CSS Grid cards; NEVER cram into one Mermaid diagram                     |
| Data tables, comparisons, audits, feature matrices                                       | `./templates/data-table.html`, `./references/data-tables.md`                                                                                                    | Real semantic HTML `<table>`; REQUIRED for ASCII-table threshold                                                      |
| Slide decks                                                                              | `./templates/slide-deck.html`, `./references/slide-patterns.md`, `./references/slide-deck-mode.md`, `./references/css-patterns.md`, `./references/libraries.md` | Opt-in only; one viewport per slide; complete source coverage                                                         |
| Prose-heavy publishable pages                                                            | `./references/css-patterns.md`, `./references/libraries.md`                                                                                                     | Prose Page Elements and Typography by Content Voice; transform prose into visual structure                            |
| CSS/layout, SVG connectors, depth, collapsibles, overflow, code blocks, image containers | `./references/css-patterns.md`                                                                                                                                  | Reuse established patterns; protect against overflow and unreadable code                                              |
| Visual direction, palettes, forbidden aesthetics                                         | `./references/visual-style.md`, `./references/libraries.md`                                                                                                     | Pick one distinctive aesthetic; typography carries the design; avoid AI-slop signals                                  |
| Pages with 4+ sections                                                                   | `./references/responsive-nav.md`                                                                                                                                | Add responsive navigation                                                                                             |
| AI-generated illustrations                                                               | `./references/ai-illustrations.md`                                                                                                                              | Optional; use only when imagery explains what CSS/Mermaid cannot                                                      |
| Sharing pages                                                                            | `./commands/share.md`                                                                                                                                           | `uv run --script {{skill_dir}}/scripts/cli.py share <html-file>`                                                      |

## Rendering Dispatch

| Content type                           | Approach                                                     | Constraint                                                                                   |
| -------------------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| Architecture, text-heavy               | CSS Grid cards + flow arrows                                 | Use when descriptions, code refs, tool lists, or rich card content matter more than topology |
| Architecture, simple topology          | Mermaid                                                      | Under 10 elements; visible relationships need automatic edge routing                         |
| Architecture, complex                  | Hybrid Mermaid overview + CSS Grid cards                     | 15+ elements NEVER cram into one Mermaid diagram                                             |
| Flowchart / pipeline                   | Mermaid                                                      | Prefer `flowchart TD`; LR only for 3-4 node linear flows                                     |
| Sequence diagram                       | Mermaid                                                      | Use lifelines, messages, activation boxes, notes, loops                                      |
| Data flow                              | Mermaid with edge labels                                     | Emphasize data connections; use thicker/colored primary edges                                |
| ER / schema diagram                    | Mermaid                                                      | Use `erDiagram`; prefer over class diagrams for pure data modeling                           |
| State machine / decision tree          | Mermaid                                                      | Use `stateDiagram-v2` only for simple labels; complex labels require `flowchart TD`          |
| Mind map                               | Mermaid                                                      | Use `mindmap` for hierarchical branching                                                     |
| Class diagram                          | Mermaid                                                      | Use for OOP/domain models with methods, inheritance, composition, aggregation                |
| C4 architecture                        | Mermaid flowchart                                            | Use `flowchart TD`/`graph TD` + `subgraph`; NEVER native `C4Context`                         |
| Data table                             | HTML `<table>`                                               | REQUIRED for ASCII-table threshold; semantic, accessible, copy-pasteable                     |
| Timeline / roadmap                     | CSS central line + cards                                     | Linear layout does not need a graph engine                                                   |
| Dashboard / metrics                    | CSS Grid + Chart.js                                          | Use KPI cards, inline SVG sparklines, CSS progress bars, Chart.js via CDN for real charts    |
| Documentation / README / API reference | Cards, numbered flows, tables, side-by-side panels, callouts | Transform prose structure; NEVER merely restyle paragraphs                                   |

## Output Contract

Every diagram is a single self-contained `.html` file written to `~/.agent/diagrams/` with a descriptive filename such as `modem-architecture.html`, `pipeline-flow.html`, or `schema-overview.html`.

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Descriptive Title</title>
    <link
      href="https://fonts.googleapis.com/css2?family=...&display=swap"
      rel="stylesheet"
    />
    <style>
      /* CSS custom properties, theme, layout, components — all inline */
    </style>
  </head>
  <body>
    <!-- Semantic HTML: sections, headings, lists, tables, inline SVG -->
    <!-- No script needed for static CSS-only diagrams -->
    <!-- Optional: <script> for Mermaid, Chart.js, or anime.js when used -->
  </body>
</html>
```

Open in browser:

```text
open ~/.agent/diagrams/filename.html
xdg-open ~/.agent/diagrams/filename.html
```

Tell the user the exact file path so they can re-open or share it.

## Hard Aesthetic Rules

- Pick one aesthetic and commit. Vary recent choices; if replacing styling with a generic dark theme would not change the page's identity, redesign it.
- Typography MUST carry the design. Pick a distinctive pairing from `./references/libraries.md`; rotate pairings across generations. Load fonts with `<link>` in `<head>` and include system fallbacks.
- Color MUST use CSS custom properties. Define at minimum `--bg`, `--surface`, `--border`, `--text`, `--text-dim`, and 3-5 accents with dim variants.
- Build depth through 2-4% lightness shifts, low-opacity borders, restrained shadows, subtle grids, and gentle radial atmosphere. Hero sections SHOULD dominate the first viewport.
- Animation MUST earn its place. Continuous post-load motion is forbidden except progress indicators. Always implement `prefers-reduced-motion`.
- NEVER use generic AI-slop aesthetics: neon dashboard, gradient mesh, cyan-magenta-pink accents, gradient heading text, glowing box-shadows, pulsing static content, emoji header icons, identical icon-card sections, centered-everything layouts, three-dot code chrome, or purple/pink/cyan background blobs. See `./references/visual-style.md`.

## Implementation Plans and Code Views

The goal is understanding, not source dumping. NEVER inline full files unless the user explicitly asks for complete source. Show file structure with one-line descriptions, 5-10 line key snippets, collapsible full code only when truly needed, API/interface summary, and usage examples.

Code blocks MUST use explicit formatting from `./references/css-patterns.md`, including `white-space: pre-wrap`, otherwise code collapses into unreadable walls.

<yielding>
## Validation Checklist

Before delivering, verify:

- Squint test: hierarchy remains visible when blurred.
- Swap test: replacing fonts/colors with a generic dark theme would materially weaken the page.
- Both themes: light and dark modes look intentional via `prefers-color-scheme`.
- Reduced motion: `prefers-reduced-motion` disables nonessential animation.
- Information completeness: the page answers the user's request; pretty but incomplete is failure.
- No overflow: resize across widths; nothing clips or escapes. Every grid/flex child needs `min-width: 0`. Side-by-side panels need `overflow-wrap: break-word`. Code blocks need `white-space: pre-wrap`. NEVER use `display: flex` on `<li>` for marker characters; use absolute positioning for markers instead. See Overflow Protection in `./references/css-patterns.md`.
- Mermaid usability: every `.mermaid-wrap` has zoom controls, pan, Ctrl/Cmd+scroll zoom, reset, expand, and click-to-expand.
- File opens cleanly: no console errors, broken font loads, or layout shifts.

If a generated page violates a critical rule, fix the HTML before responding. NEVER explain around a broken visual artifact.
</yielding>
