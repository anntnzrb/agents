---
name: visual-explainer
description: Generate beautiful, self-contained HTML pages that visually explain systems, code changes, plans, and data. Use when the user asks for a diagram, architecture overview, diff review, plan review, project recap, comparison table, or any visual explanation of technical concepts. Also use proactively when you are about to render a complex ASCII table (4+ rows or 3+ columns) — present it as a styled HTML page instead.
license: GPL-3.0-or-later
compatibility: Requires a browser to view generated HTML files. Optional surf-cli for AI image generation.
metadata:
  author: anntnzrb
allowed-tools: ""
disable-model-invocation: true
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

| Command | What it does |
|---------|-------------|
| `generate-web-diagram` | Generate an HTML diagram for any topic |
| `generate-visual-plan` | Generate a visual implementation plan for a feature |
| `generate-slides` | Generate a magazine-quality slide deck |
| `diff-review` | Visual diff review with architecture comparison and code review |
| `plan-review` | Compare a plan against the codebase with risk assessment |
| `project-recap` | Mental model snapshot for context-switching back to a project |
| `fact-check` | Verify accuracy of a document against actual code |
| `share` | Deploy an HTML page to Vercel and get a live URL |

<workflow>
## Core Workflow

1. Choose a direction before writing HTML. NEVER default to generic dark-blue technical styling.
2. Determine audience and density: developer system model, PM overview, team proposal review, data audit, prose explanation, or slide presentation.
3. Treat visual structure as default. Essays, READMEs, articles, and docs become cards, diagrams, grids, timelines, callouts, or tables; prose blocks are accents, not the page mode.
4. Read the relevant template/reference before generating:
   - Text-heavy architecture overviews: `./templates/architecture.html`
   - Flowcharts, sequence diagrams, ER, state machines, mind maps, class diagrams, C4: `./templates/mermaid-flowchart.html`
   - Data tables, comparisons, audits, feature matrices: `./templates/data-table.html`
   - Slide decks: `./templates/slide-deck.html` and `./references/slide-patterns.md`
   - Prose-heavy publishable pages: "Prose Page Elements" in `./references/css-patterns.md` and "Typography by Content Voice" in `./references/libraries.md`
   - CSS/layout patterns, SVG connectors, depth tiers, collapsibles, overflow protection, code blocks, and image containers: `./references/css-patterns.md`
   - Pages with 4+ sections: `./references/responsive-nav.md`
5. Write one self-contained `.html` file. External assets are limited to CDN links for fonts and optional libraries.
6. Open the file in a browser and inspect it from the user's perspective before responding.
</workflow>

## Rendering Dispatch

| Content type | Approach | Constraint |
|---|---|---|
| Architecture, text-heavy | CSS Grid cards + flow arrows | Use when descriptions, code refs, tool lists, or rich card content matter more than topology |
| Architecture, simple topology | Mermaid | Under 10 elements; visible relationships need automatic edge routing |
| Architecture, complex | Hybrid Mermaid overview + CSS Grid cards | 15+ elements NEVER cram into one Mermaid diagram |
| Flowchart / pipeline | Mermaid | Prefer `flowchart TD`; LR only for 3-4 node linear flows |
| Sequence diagram | Mermaid | Use lifelines, messages, activation boxes, notes, loops |
| Data flow | Mermaid with edge labels | Emphasize data connections; use thicker/colored primary edges |
| ER / schema diagram | Mermaid | Use `erDiagram`; prefer over class diagrams for pure data modeling |
| State machine / decision tree | Mermaid | Use `stateDiagram-v2` only for simple labels; complex labels require `flowchart TD` |
| Mind map | Mermaid | Use `mindmap` for hierarchical branching |
| Class diagram | Mermaid | Use for OOP/domain models with methods, inheritance, composition, aggregation |
| C4 architecture | Mermaid flowchart | Use `flowchart TD`/`graph TD` + `subgraph`; NEVER native `C4Context` |
| Data table | HTML `<table>` | REQUIRED for ASCII-table threshold; semantic, accessible, copy-pasteable |
| Timeline / roadmap | CSS central line + cards | Linear layout does not need a graph engine |
| Dashboard / metrics | CSS Grid + Chart.js | Use KPI cards, inline SVG sparklines, CSS progress bars, Chart.js via CDN for real charts |
| Documentation / README / API reference | Cards, numbered flows, tables, side-by-side panels, callouts | Transform prose structure; NEVER merely restyle paragraphs |

## Mermaid Rules

Use Mermaid when automatic edge routing or specialized syntax materially improves comprehension. Apply these constraints together:

| Area | Rule |
|---|---|
| Template | NEVER use bare `<pre class="mermaid">`. Always copy the full `diagram-shell` pattern from `templates/mermaid-flowchart.html`: `.diagram-shell` > `.mermaid-wrap` > `.zoom-controls` + `.mermaid-viewport` > `.mermaid-canvas`, CSS, and the JS module for zoom/pan/fit. |
| Controls | Every `.mermaid-wrap` MUST include +/−/reset/expand controls, Ctrl/Cmd+scroll zoom, click-and-drag pan, and click-to-expand/open full-size. Preserve `openMermaidInNewTab()` behavior from `./references/css-patterns.md`. |
| Theme | Use `theme: 'base'` with custom `themeVariables` so Mermaid matches page palette. Use `layout: 'elk'` for complex graphs only with the `@mermaid-js/layout-elk` CDN import from `./references/libraries.md`. |
| Scaling | 10-12 nodes require `fontSize` 18-20px and `INITIAL_ZOOM` 1.5-1.6. 15+ elements require the hybrid pattern: simple Mermaid overview plus detailed CSS Grid cards. |
| Direction | Prefer `flowchart TD`/`graph TD`. Use LR only for simple 3-4 node linear flows. |
| Labels | Use `<br/>` inside quoted flowchart labels. NEVER use escaped newlines like `\n`; Mermaid renders them as literal text in HTML. Example: `A["Copilot Backend<br/>/api + /api/voicebot"]`. |
| CSS collision | NEVER define `.node` as page-level CSS. Mermaid uses `.node` internally for positioned SVG groups. Use `.ve-card` for page cards. Mermaid node styling MUST be scoped under `.mermaid` such as `.mermaid .node rect`. |
| C4 | Use flowchart syntax with `subgraph` boundaries. Persons: `(("Name"))`; systems: `["Name"]`; databases: `[("Name")]`; relationships: `-->|"protocol"|`; external systems MAY use dashed `classDef`. Native `C4Context` ignores custom themes and is forbidden. |
| State labels | If labels include colons, parentheses, `<br/>`, HTML entities, function names, or multi-line text, use `flowchart TD` with quoted edge labels instead of `stateDiagram-v2`. |

## Visual Style

Pick one aesthetic and commit. Vary recent choices; if replacing styling with a generic dark theme would not change the page's identity, redesign it.

| Aesthetic | Use when | Requirements |
|---|---|---|
| Blueprint | Technical systems, plans, architecture | Subtle grid, deep slate/blue, monospace labels, precise borders |
| Editorial | Reviews, narratives, proposals | Serif headlines such as Instrument Serif or Crimson Pro, generous whitespace, muted earth tones or deep navy + gold |
| Paper/ink | Explainers, docs, approachable plans | Warm cream `#faf7f5`, terracotta/sage, tactile informal feel |
| Monochrome terminal | CLI/tooling/system internals | Green/amber on near-black, monospace-forward, restrained CRT effect |
| IDE-inspired | Code-centric topics | Borrow a real named palette exactly: Dracula, Nord, Catppuccin Mocha/Latte, Solarized Dark/Light, Gruvbox, One Dark, Rosé Pine |
| Data-dense | Audits, matrices, dashboards | Small type, tight spacing, high information density, muted colors |

Typography MUST carry the design. Pick a distinctive pairing from `./references/libraries.md`; rotate pairings across generations. Good defaults include DM Sans + Fira Code, Instrument Serif + JetBrains Mono, IBM Plex Sans + IBM Plex Mono, Bricolage Grotesque + Fragment Mono, and Plus Jakarta Sans + Azeret Mono. Load fonts with `<link>` in `<head>` and include system fallbacks.

Color MUST use CSS custom properties. Define at minimum `--bg`, `--surface`, `--border`, `--text`, `--text-dim`, and 3-5 accents with dim variants. Prefer semantic names such as `--pipeline-step`. Use intentional palettes such as terracotta/sage (`#c2410c`, `#65a30d`), teal/slate (`#0891b2`, `#0369a1`), rose/cranberry (`#be123c`, `#881337`), amber/emerald (`#d97706`, `#059669`), or deep blue/gold (`#1e3a5f`, `#d4a73a`).

```css
/* Light-first: editorial, paper/ink, blueprint */
:root { /* light values */ }
@media (prefers-color-scheme: dark) { :root { /* dark values */ } }

/* Dark-first: IDE-inspired, terminal */
:root { /* dark values */ }
@media (prefers-color-scheme: light) { :root { /* light values */ } }
```

Build depth through 2-4% lightness shifts, low-opacity borders, restrained shadows, subtle grids, and gentle radial atmosphere. Hero sections SHOULD dominate the first viewport. Reference sections SHOULD be compact and MAY use `<details>/<summary>`. Use depth tiers from `./references/css-patterns.md`: hero, elevated, default, recessed.

Animation MUST earn its place: entrance reveals, hover feedback, SVG connector draw-ins, count-up hero values, and user-initiated interactions are acceptable. Continuous post-load motion is forbidden except progress indicators. Always implement `prefers-reduced-motion`.

<critical>
## Forbidden Aesthetics

These are AI-slop signals. If two or more appear, regenerate with Editorial, Blueprint, Paper/ink, or a real IDE palette.

| Category | NEVER use |
|---|---|
| Themes | Neon dashboard; gradient mesh; generic dark theme with cyan-magenta-pink accents |
| Font body | Inter, Roboto, Arial, Helvetica, or `system-ui` alone as primary `--font-body` |
| Accent colors | `#8b5cf6`, `#7c3aed`, `#a78bfa`, `#d946ef`, Tailwind purple/pink/cyan defaults, cyan-magenta-pink combos |
| Text effects | Gradient heading text using `background-clip: text`; identical gradient KPI treatment |
| Shadows/motion | Glowing box-shadows, animated glow keyframes, pulsing/breathing static content, continuous decorative animation after load |
| Headers | Emoji header icons; every section using the same icon-in-rounded-box pattern |
| Layout | Perfectly centered everything, identical cards everywhere, symmetric mirrored halves, every section with equal visual weight |
| Templates | Three-dot window chrome on code blocks; "neon dashboard"; pink/purple/cyan background blobs |

Required replacements: styled monospace labels, colored dot indicators, numbered badges, asymmetric dividers, inline SVG icons only when meaningful, simple code headers with filename/language labels, and varied KPI hierarchy.
</critical>

## Data Tables

Use real `<table>` markup, not CSS Grid pretending to be a table. Implement sticky `<thead>`, subtle alternating rows, optional sticky first column, responsive wrapper with `overflow-x: auto`, width hints via `<colgroup>` or `th`, hover highlighting, natural text wrapping, `<code>` for technical references, dimmed `<small>` secondary detail, and `tabular-nums` for numeric columns.

Status indicators MUST be styled elements, not emoji: green match/pass/yes, red gap/fail/no, amber partial/warning, muted neutral/info.

## Implementation Plans and Code Views

The goal is understanding, not source dumping. NEVER inline full files unless the user explicitly asks for complete source. Show file structure with one-line descriptions, 5-10 line key snippets, collapsible full code only when truly needed, API/interface summary, and usage examples.

Code blocks MUST use explicit formatting from `./references/css-patterns.md`, including `white-space: pre-wrap`, otherwise code collapses into unreadable walls.

## AI-Generated Illustrations

AI imagery is OPTIONAL. Check availability with `which surf`. If unavailable, skip images without error; the page MUST stand on CSS, typography, and structure alone.

```text
# Generate to a temp file, then base64-embed it with the platform-native tool available in your environment.
surf gemini "descriptive prompt" --generate-image <temp-image-path> --aspect-ratio 16:9
# <img src="data:image/png;base64,..." alt="descriptive alt text">
```

Use images for hero tone, conceptual illustrations, user journeys, mental models, or educational visuals Mermaid/CSS cannot express. NEVER use generic decoration, data-distracting imagery, or images for content Mermaid/CSS handles well. Match prompt style, palette, and aspect ratio to the page (`16:9` hero, `1:1` inline).

## Slide Deck Mode

Slide decks are opt-in only. Generate slides only when the user invokes `/generate-slides`, passes `--slides` to a prompt such as `/diff-review --slides`, or explicitly asks for a slide deck. NEVER auto-select slide format.

Before generating slides, read `./references/slide-patterns.md`, `./templates/slide-deck.html`, `./references/css-patterns.md`, and `./references/libraries.md`. Slides are not scrollable pages reformatted: each slide is exactly one viewport (`100dvh`), typography is 2-3× larger, compositions are bolder, and the deck needs a narrative arc such as impact → context → deep dive → resolution.

Content completeness is REQUIRED. Inventory the source, map every item to slides, and verify coverage before writing HTML. Every section, decision, data point, specification, and collapsible detail from the source MUST appear. Add slides rather than cutting content. Consecutive slides MUST vary spatial approach: centered, left-heavy, right-heavy, split, edge-aligned, full-bleed. Three centered slides in a row is a failure.

Use the 10 slide types from `slide-patterns.md`: Title, Section Divider, Content, Split, Diagram, Dashboard, Table, Code, Quote, Full-Bleed. Content that exceeds density limits splits across slides; it NEVER scrolls within a slide. If surf-cli is available, generate 2-4 images for title/background/optional illustrations before writing HTML.

When `--slides` is passed to `/diff-review`, `/plan-review`, `/project-recap`, or another prompt, gather data using that prompt's normal instructions, then present the same breadth of content as a slide deck. The slide format is NEVER an excuse to summarize away sections.

## File Structure

Every diagram is a single self-contained `.html` file:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Descriptive Title</title>
  <link href="https://fonts.googleapis.com/css2?family=...&display=swap" rel="stylesheet">
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

## Deliver

Write to `~/.agent/diagrams/` with a descriptive filename such as `modem-architecture.html`, `pipeline-flow.html`, or `schema-overview.html`.

Open in browser:

```text
open ~/.agent/diagrams/filename.html
xdg-open ~/.agent/diagrams/filename.html
```

Tell the user the file path so they can re-open or share it.

## Sharing Pages

Share pages via Vercel. No account or authentication is required.

```text
uv run --script {{skill_dir}}/scripts/cli.py share <html-file>
```

Example:

```text
uv run --script {{skill_dir}}/scripts/cli.py share ~/.agent/diagrams/my-diagram.html

# Output:
# Shared successfully!
# Live URL:  https://skill-deploy-abc123.vercel.app
# Claim URL: https://vercel.com/claim-deployment?code=...
```

How it works:
1. Copies HTML file to temp directory as `index.html`
2. Deploys via the vercel-deploy skill (zero-auth claimable deployment)
3. URL is live immediately — works in any browser

Requirements:
- vercel-deploy skill (should be pre-installed; if not: `pi install npm:vercel-deploy`)

Notes:
- Deployments are public — anyone with the URL can view
- Preview deployments have configurable retention (default: 30 days)
- Claim URL lets you transfer the deployment to your Vercel account

See `./commands/share.md` for the `/share` command template.

<yielding>
## Quality Checks

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