# Renderer and state contract

Read this before implementing a chart component or route-level interaction.

## Renderer ladder

Start with semantic HTML and CSS when a table, list, or small multiples answer the task. Use SVG for inspectable marks, labels, focus targets, print/export, and moderate point counts. Use Canvas when many marks make SVG costly; retain a DOM summary/table, keyboard navigation model, hit-testing strategy, and device-pixel-ratio handling. Use WebGL only for very large or continuously animated datasets; document GPU fallback, precision limits, context loss, and a non-WebGL accessible path.

Every renderer follows the same grammar: data → scales/domains → marks → annotations → interaction state → accessible explanation. Keep scales and formatting deterministic; never let a renderer silently change the claim. Preserve a stable testable data model independent of drawing code.

## React ownership

The route/data boundary owns fetching, cache invalidation, permissions, and durable filters. The nearest common owner owns selections shared by sibling charts. Put shareable filters, time range, sort, and focused entity in URL state; parse, validate, canonicalize, and replace history for transient edits. The chart owns hover, pointer geometry, animation progress, and renderer internals. A route change must not strand state in an unmounted chart or create two competing sources of truth.

Use stable IDs and explicit controlled props for selection. Synchronize URL state through the router rather than ad hoc global listeners. Keep serialization compact and versionable; exclude secrets, raw datasets, and hover coordinates. On reload or shared link, invalid parameters must fall back safely and visibly.

## Interaction and fallback contract

Provide zoom/pan/reset alternatives, keyboard focus and equivalent value inspection, loading/empty/error states, and an accessible text, table, or data-download fallback suited to the task. Ensure mobile controls do not depend on hover, preserve readable labels, and avoid horizontal overflow. Export must use the same filtered, labeled data and units shown in the view.

## Sources

- https://react.dev/learn/sharing-state-between-components
- https://url.spec.whatwg.org/
- https://developer.mozilla.org/en-US/docs/Web/SVG
- https://developer.mozilla.org/en-US/docs/Web/API/Canvas_API
- https://registry.khronos.org/webgl/specs/latest/1.0/
