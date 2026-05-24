# Mermaid Rules

Use Mermaid when automatic edge routing or specialized syntax materially improves comprehension. Apply these constraints together.

| Area | Rule |
|---|---|
| Template | NEVER use bare `<pre class="mermaid">`. Always copy the full `diagram-shell` pattern from `../templates/mermaid-flowchart.html`: `.diagram-shell` > `.mermaid-wrap` > `.zoom-controls` + `.mermaid-viewport` > `.mermaid-canvas`, CSS, and the JS module for zoom/pan/fit. |
| Controls | Every `.mermaid-wrap` MUST include +/−/reset/expand controls, Ctrl/Cmd+scroll zoom, click-and-drag pan, and click-to-expand/open full-size. Preserve `openMermaidInNewTab()` behavior from `./css-patterns.md`. |
| Theme | Use `theme: 'base'` with custom `themeVariables` so Mermaid matches page palette. Use `layout: 'elk'` for complex graphs only with the `@mermaid-js/layout-elk` CDN import from `./libraries.md`. |
| Scaling | 10-12 nodes require `fontSize` 18-20px and `INITIAL_ZOOM` 1.5-1.6. 15+ elements require the hybrid pattern: simple Mermaid overview plus detailed CSS Grid cards. |
| Direction | Prefer `flowchart TD`/`graph TD`. Use LR only for simple 3-4 node linear flows. |
| Labels | Use `<br/>` inside quoted flowchart labels. NEVER use escaped newlines like `\n`; Mermaid renders them as literal text in HTML. Example: `A["Copilot Backend<br/>/api + /api/voicebot"]`. |
| CSS collision | NEVER define `.node` as page-level CSS. Mermaid uses `.node` internally for positioned SVG groups. Use `.ve-card` for page cards. Mermaid node styling MUST be scoped under `.mermaid` such as `.mermaid .node rect`. |
| C4 | Use flowchart syntax with `subgraph` boundaries. Persons: `(("Name"))`; systems: `["Name"]`; databases: `[("Name")]`; relationships: `-->|"protocol"|`; external systems MAY use dashed `classDef`. Native `C4Context` ignores custom themes and is forbidden. |
| State labels | If labels include colons, parentheses, `<br/>`, HTML entities, function names, or multi-line text, use `flowchart TD` with quoted edge labels instead of `stateDiagram-v2`. |
