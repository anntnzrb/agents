---
name: data-visualization-engineering
description: Engineer truthful, accessible, shareable data visualizations in web products and React applications.
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb
  provenance: Clean-room original guidance; informed by the linked primary standards and documentation, not copied from plugins or templates.
---

# Data Visualization Engineering

Use this skill when building, reviewing, or repairing an analytical chart, dashboard, or interactive data view. Start with the user’s decision or claim—not a chart type, library, or visual style.

## Core workflow

1. State the task: comparison, trend, distribution, composition, relationship, location, flow, or a precise lookup
2. State the claim the view is allowed to make, its population, measure, time window, unit, and transformation. If any are unknown, expose that uncertainty rather than implying certainty
3. Choose the least-complex encoding that lets the intended audience verify the claim. Keep scales, baselines, binning, sorting, filters, and annotations inspectable
4. Define the rendering and state contract before implementation: data shape, domains, interaction state, loading/error/empty states, ownership, URL representation, and exportable data
5. Build the accessible mobile path alongside the graphic: semantic heading and summary, keyboard-equivalent interactions, non-color cues, a responsive layout, and an accessible text, table, or data-download fallback suited to the task
6. Test the data, visual encoding, interactions, export, and assistive path as separate layers
7. Evaluate recorded evidence against the stated claim and delivery contract; iterate on data, encoding, interaction, or assistive defects before shipping

## Non-negotiable truthfulness

- Do not use a truncated quantitative axis unless the design makes the truncation unmistakable and the chart type still supports comparison. Bar lengths normally require a zero baseline
- Label units, denominators, dates, aggregation, adjustments, exclusions, and source. Distinguish observed values, estimates, forecasts, and targets
- Show uncertainty where it materially changes the conclusion: intervals, ranges, sample size, missingness, or an explicit note that uncertainty is unavailable. Never turn a model output into a measured fact
- Do not encode a ranked claim with unsorted data, a time claim with an unordered axis, or a part-to-whole claim with categories that do not share a whole
- Preserve the raw values used by the visualization so users can inspect or export them

## Follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Choose a chart and disclose uncertainty | `references/chart-selection-and-uncertainty.md` | Before selecting marks, scales, or a narrative claim |
| Select a renderer and own React state | `references/renderer-and-state-contract.md` | Before writing a chart component or cross-route interaction |
| Verify behavior, accessibility, and export | `references/visualization-qa.md` | Before shipping or reviewing a visualization |

## Delivery contract

Deliver the decision question, chart title/subtitle, source and data currency, visible caveats, accessible summary, and an accessible text, table, or data-download fallback suited to the task. Make controls reversible and keyboard-operable. Keep a shareable URL limited to stable, user-meaningful view state; never serialize secrets, raw records, or ephemeral hover state.

For React, put server data at the route/data boundary, shared filters and selections in the nearest common owner or URL, and local rendering details inside the chart. Do not duplicate the same state across route, store, and component.

## Authoritative starting points

- [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- [WAI-ARIA Authoring Practices Guide](https://www.w3.org/WAI/ARIA/apg/patterns/)
- [React: sharing state between components](https://react.dev/learn/sharing-state-between-components)
- [WHATWG URL Standard](https://url.spec.whatwg.org/)
- [MDN Canvas API](https://developer.mozilla.org/en-US/docs/Web/API/Canvas_API)
- [Khronos WebGL specification](https://registry.khronos.org/webgl/specs/latest/1.0/)
