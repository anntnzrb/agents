# Visualization QA

Read this before shipping or reviewing a visualization.

## Layered checks

1. **Data:** fixture totals, units, joins, sorting, domains, nulls, duplicate IDs, timezone, aggregation, and source freshness. Reconcile visible totals to raw/exported values
2. **Encoding:** baseline, scale, tick formatting, legend, labels, annotations, interval semantics, color contrast, and no-color-only distinctions. Compare the rendered claim with the written claim
3. **Interaction:** keyboard path, focus order, tooltip/value inspection, zoom/pan/reset, filtering, selection, back/forward, reload, deep link, and invalid URL parameters. Test loading, empty, partial, and error states
4. **Responsive:** narrow mobile viewport, text zoom, landscape, touch targets, long labels, dense data, and no clipped controls or horizontal overflow. Provide a readable table or list fallback
5. **Assistive technology:** heading and chart summary, semantic table, meaningful labels, focus visibility, live updates, reduced motion, and screen-reader access to exact values. Never rely on the pixels alone
6. **Export:** CSV/JSON/image output carries source, units, filters, date range, labels, and uncertainty notes; exported values match the current view and remain legible in print
7. **Performance/resilience:** representative large data, resize, device-pixel ratio, slow network, renderer fallback, GPU context loss where relevant, and no interaction frame stalls

Record evidence by layer, viewport, browser/AT, dataset, and renderer. Fix data and contract defects before cosmetic polish; a screenshot is not proof of truthfulness or accessibility.

## Sources

- https://www.w3.org/TR/WCAG22/
- https://www.w3.org/WAI/ARIA/apg/
- https://developer.mozilla.org/en-US/docs/Web/Accessibility
- https://web.dev/articles/vitals
- https://www.w3.org/TR/SVG/access.html
