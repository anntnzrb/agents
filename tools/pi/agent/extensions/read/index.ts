import { createReadToolDefinition, DEFAULT_MAX_BYTES, formatSize, type ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";
import { getFirstTextContent } from "../_shared/tool-utils.js";

type ReadArgs = {
	path?: unknown;
	file_path?: unknown;
	offset?: unknown;
	limit?: unknown;
};

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

const asString = (value: unknown): string | undefined => (typeof value === "string" ? value : undefined);

const asPositiveInteger = (value: unknown): number | undefined =>
	typeof value === "number" && Number.isInteger(value) && value > 0 ? value : undefined;

const getReadRange = (args: ReadArgs): string | undefined => {
	const offset = asPositiveInteger(args.offset);
	const limit = asPositiveInteger(args.limit);
	if (offset === undefined && limit === undefined) return undefined;
	const start = offset ?? 1;
	if (limit === undefined) return `L[${start}-]`;
	return `L[${start}-${start + limit - 1}]`;
};

const buildReadCallText = (
	args: ReadArgs,
	theme: { fg: (token: string, text: string) => string; bold: (text: string) => string },
): string => {
	const rawPath = asString(args.path) ?? asString(args.file_path) ?? "...";
	const segments = [`${theme.fg("muted", "☰")} ${theme.fg("toolTitle", theme.bold("read"))} ${theme.fg("muted", rawPath)}`];
	const range = getReadRange(args);
	if (range) segments.push(range);
	return segments.join(theme.fg("dim", " · "));
};

const buildReadResultText = (details: ReadDetails, theme: { fg: (token: string, text: string) => string }): string => {
	const truncation = details.truncation;
	if (!truncation?.truncated) return "";

	if (truncation.firstLineExceedsLimit) {
		return theme.fg("warning", `${formatSize(truncation.maxBytes ?? DEFAULT_MAX_BYTES)} limit`);
	}
	if (truncation.truncatedBy === "lines") {
		return theme.fg("warning", `${truncation.maxLines ?? "?"} lines`);
	}
	return theme.fg("warning", `${formatSize(truncation.maxBytes ?? DEFAULT_MAX_BYTES)} limit`);
};

export const __test = {
	buildReadCallText,
	buildReadResultText,
	getReadRange,
};

export default function readExtension(pi: ExtensionAPI): void {
	const baseRead = createReadToolDefinition(process.cwd());

	pi.registerTool({
		...baseRead,
		renderShell: "self",
		renderCall(args, theme, context) {
			const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
			text.setText(buildReadCallText((args ?? {}) as ReadArgs, theme));
			return text;
		},
		renderResult(result, _options, theme, context) {
			const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
			const rawText = getFirstTextContent(result.content as ReadResultPart[]);

			if (context.isError) {
				text.setText(theme.fg("error", rawText || "(no output)"));
				return text;
			}

			text.setText(buildReadResultText((result.details ?? {}) as ReadDetails, theme));
			return text;
		},
	});
}
