# Slide Deck Mode

Slide decks are opt-in only. Generate slides only when the user invokes `/generate-slides`, passes `--slides` to a prompt such as `/diff-review --slides`, or explicitly asks for a slide deck. NEVER auto-select slide format.

Before generating slides, read `./slide-patterns.md`, `../templates/slide-deck.html`, `./css-patterns.md`, and `./libraries.md`. Slides are not scrollable pages reformatted: each slide is exactly one viewport (`100dvh`), typography is 2-3× larger, compositions are bolder, and the deck needs a narrative arc such as impact → context → deep dive → resolution.

Content completeness is REQUIRED. Inventory the source, map every item to slides, and verify coverage before writing HTML. Every section, decision, data point, specification, and collapsible detail from the source MUST appear. Add slides rather than cutting content. Consecutive slides MUST vary spatial approach: centered, left-heavy, right-heavy, split, edge-aligned, full-bleed. Three centered slides in a row is a failure.

Use the 10 slide types from `slide-patterns.md`: Title, Section Divider, Content, Split, Diagram, Dashboard, Table, Code, Quote, Full-Bleed. Content that exceeds density limits splits across slides; it NEVER scrolls within a slide. If surf-cli is available, generate 2-4 images for title/background/optional illustrations before writing HTML.

When `--slides` is passed to `/diff-review`, `/plan-review`, `/project-recap`, or another prompt, gather data using that prompt's normal instructions, then present the same breadth of content as a slide deck. The slide format is NEVER an excuse to summarize away sections.
