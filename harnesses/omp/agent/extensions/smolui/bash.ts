import { elideSection } from "./transforms.ts";

// Hide the Output rows; keep the `⟨Wall | Timeout | Exit⟩` metadata row.
export default elideSection(1, (text, theme) => text.startsWith(theme.format.bracketLeft));
