# Visual Style and Forbidden Aesthetics

Pick one aesthetic and commit. Vary recent choices; if replacing styling with a generic dark theme would not change the page's identity, redesign it.

## Aesthetics

| Aesthetic | Use when | Requirements |
|---|---|---|
| Blueprint | Technical systems, plans, architecture | Subtle grid, deep slate/blue, monospace labels, precise borders |
| Editorial | Reviews, narratives, proposals | Serif headlines such as Instrument Serif or Crimson Pro, generous whitespace, muted earth tones or deep navy + gold |
| Paper/ink | Explainers, docs, approachable plans | Warm cream `#faf7f5`, terracotta/sage, tactile informal feel |
| Monochrome terminal | CLI/tooling/system internals | Green/amber on near-black, monospace-forward, restrained CRT effect |
| IDE-inspired | Code-centric topics | Borrow a real named palette exactly: Dracula, Nord, Catppuccin Mocha/Latte, Solarized Dark/Light, Gruvbox, One Dark, Rosé Pine |
| Data-dense | Audits, matrices, dashboards | Small type, tight spacing, high information density, muted colors |

Typography MUST carry the design. Pick a distinctive pairing from `./libraries.md`; rotate pairings across generations. Good defaults include DM Sans + Fira Code, Instrument Serif + JetBrains Mono, IBM Plex Sans + IBM Plex Mono, Bricolage Grotesque + Fragment Mono, and Plus Jakarta Sans + Azeret Mono. Load fonts with `<link>` in `<head>` and include system fallbacks.

Color MUST use CSS custom properties. Define at minimum `--bg`, `--surface`, `--border`, `--text`, `--text-dim`, and 3-5 accents with dim variants. Prefer semantic names such as `--pipeline-step`. Use intentional palettes such as terracotta/sage (`#c2410c`, `#65a30d`), teal/slate (`#0891b2`, `#0369a1`), rose/cranberry (`#be123c`, `#881337`), amber/emerald (`#d97706`, `#059669`), or deep blue/gold (`#1e3a5f`, `#d4a73a`).

```css
/* Light-first: editorial, paper/ink, blueprint */
:root { /* light values */ }
@media (prefers-color-scheme: dark) { :root { /* dark values */ } }

/* Dark-first: IDE-inspired, terminal */
:root { /* dark values */ }
@media (prefers-color-scheme: light) { :root { /* light values */ } }
```

Build depth through 2-4% lightness shifts, low-opacity borders, restrained shadows, subtle grids, and gentle radial atmosphere. Hero sections SHOULD dominate the first viewport. Reference sections SHOULD be compact and MAY use `<details>/<summary>`. Use depth tiers from `./css-patterns.md`: hero, elevated, default, recessed.

Animation MUST earn its place: entrance reveals, hover feedback, SVG connector draw-ins, count-up hero values, and user-initiated interactions are acceptable. Continuous post-load motion is forbidden except progress indicators. Always implement `prefers-reduced-motion`.

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
