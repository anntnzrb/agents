import { hideSection } from "./transforms.ts";

// Hide the Output rows. The command, the `Wall · Timeout · Exit` facts in the
// bottom border, and warning-styled rows (truncation and its artifact) stay.
// On a narrow pane the facts no longer fit in the border; omp wraps them into
// the end of Output as dim rows, which stay too. Output text is styled
// `toolOutput`, so it never opens with either color.
export default hideSection(section => section.label === "Output", {
	keep: (raw, theme) => raw.startsWith(theme.getFgAnsi("warning")),
	keepTail: (raw, theme) => raw.startsWith(theme.getFgAnsi("dim")),
});
