# Chart selection and uncertainty

Read this when the chart type or confidence story is undecided.

## Claim-first choice

Write one sentence: “An audience should decide **X** about **population Y**, measured as **M**, over **time/window T**.” Then choose the simplest view:

- Comparison: sorted bars or dot plot; use aligned baselines and direct labels for few values
- Trend: line or step chart; show cadence, gaps, and meaningful zeroes
- Distribution: histogram, density, box/interval plot; disclose binning and sample size
- Relationship: scatterplot or small multiples; distinguish correlation from causation
- Composition: stacked bars or area only when the whole is stable and parts remain legible; otherwise use grouped/small multiples
- Lookup: table, matrix, or labeled dot plot; do not force a chart where exact retrieval is the task

Avoid pie/donut for many categories, dual axes that invite false equivalence, decorative 3-D, and smoothing that hides observations. Sort only when rank is the claim; preserve meaningful order for time, geography, or process.

## Honest uncertainty

Name the uncertainty type: sampling interval, model interval, measurement error, scenario range, missingness, or forecast horizon. Show intervals with a visible key and exact values on demand; do not imply an interval is a probability unless its semantics support that interpretation. Explain the denominator, confidence/credible level, method, and whether intervals account for clustering or multiple comparisons.

Mark estimates, forecasts, targets, and observed data differently in text and/or stroke/fill—not color alone. Show missing periods as gaps or explicit missing markers. If uncertainty cannot be estimated, say so and identify the likely sources instead of inventing error bars.

## Sources

- https://clauswilke.com/dataviz/ (grammar and perceptual choices)
- https://www.w3.org/WAI/WCAG22/ (non-color and text alternatives)
- https://www.nist.gov/pml/nist-technical-note-1297 (evaluating and expressing measurement uncertainty)
