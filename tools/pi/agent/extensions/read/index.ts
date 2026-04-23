import { createReadToolDefinition, DEFAULT_MAX_BYTES, formatSize, keyHint, type ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";

type ReadResultPart = {
	type: string;
	text?: string;
};

type ReadDetails = {
	truncation?: {
		truncated?: boolean;
		truncatedBy?: "lines" | "bytes" | null;
		maxBytes?: number;
		maxLines?: number;
		firstLineExceedsLimit?: boolean;
	};
};

const getResultText = (content: readonly ReadResultPart[]): string => {
	for (const part of content) {
		if (part.type === "text") return part.text ?? "";
	}
	return "";
};

const buildCollapsedReadText = (
	details: ReadDetails,
	theme: { fg: (token: string, text: string) => string },
): string => {
	const truncation = details.truncation;
	const lines: string[] = [];

	if (truncation?.truncated) {
		if (truncation.firstLineExceedsLimit) {
			lines.push(theme.fg("warning", `${formatSize(truncation.maxBytes ?? DEFAULT_MAX_BYTES)} limit`));
		} else if (truncation.truncatedBy === "lines") {
			lines.push(theme.fg("warning", `${truncation.maxLines ?? "line"} line window`));
		} else {
			lines.push(theme.fg("warning", `${formatSize(truncation.maxBytes ?? DEFAULT_MAX_BYTES)} output limit`));
		}
	}
	lines.push(theme.fg("dim", `(${keyHint("app.tools.expand", "to expand")})`));

	return lines.join("\n");
};

export default function readExtension(pi: ExtensionAPI): void {
	const baseRead = createReadToolDefinition(process.cwd());

	pi.registerTool({
		...baseRead,
		renderResult(result, options, theme, context) {
			const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
			const rawText = getResultText(result.content as ReadResultPart[]);

			if (context.isError || options.expanded || options.isPartial) {
				text.setText(rawText || "(no output)");
				return text;
			}

			text.setText(buildCollapsedReadText((result.details ?? {}) as ReadDetails, theme));
			return text;
		},
	});
}
