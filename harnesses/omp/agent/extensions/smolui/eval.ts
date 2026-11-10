import { hideSection, type View } from "./transforms.ts";

// The code pane sits under each cell's title bar, ahead of the labeled Output
// section. Success: hide it; output and display() rows stay.
const hideCode = hideSection(section => section.index === 0);

// Error: hide the code and the passing cells' output; a failed cell paints its
// traceback in the error color, so those rows stay.
const hideToTraceback = hideSection(section => section.index === 0 || section.label === "Output", {
	keep: (raw, theme) => raw.startsWith(theme.getFgAnsi("error")),
});

const evaluate: View = (lines, theme, isError) => (isError ? hideToTraceback : hideCode)(lines, theme, isError);

export default evaluate;
