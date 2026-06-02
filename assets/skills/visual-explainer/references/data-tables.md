# Data Tables

Use real `<table>` markup, not CSS Grid pretending to be a table.

Required table features:

- Sticky `<thead>`.
- Subtle alternating rows.
- Optional sticky first column when row identity matters.
- Responsive wrapper with `overflow-x: auto`.
- Width hints via `<colgroup>` or `th`.
- Hover highlighting.
- Natural text wrapping.
- `<code>` for technical references.
- Dimmed `<small>` secondary detail.
- `tabular-nums` for numeric columns.

Status indicators MUST be styled elements, not emoji:

- Green: match/pass/yes.
- Red: gap/fail/no.
- Amber: partial/warning.
- Muted: neutral/info.
