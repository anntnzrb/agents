import { elideSection, headerOnly, type Transform } from "./transforms.ts";

const hideCode = elideSection(0);

// Success: hide the code cell; Output and display() rows stay.
// Error: only the title row (status, cell title, duration); the traceback is hidden.
const evaluate: Transform = (component, options, theme, isError) =>
	isError ? headerOnly(component, options, theme) : hideCode(component, options, theme);

export default evaluate;
