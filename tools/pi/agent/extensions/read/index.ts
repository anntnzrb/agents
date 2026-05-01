import { createReadToolDefinition, DEFAULT_MAX_BYTES, formatSize, type ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { getReusableText, joinRenderSegments, type ColorTheme, type RenderTheme } from "../_shared/render-utils.js";
import { getFirstTextContent } from "../_shared/tool-utils.js";
import { asPositiveInteger, asString } from "../_shared/value-utils.js";

type ReadArgs = {
	path?: unknown;
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

const getReadRange = (args: ReadArgs): string | undefined => {
	const offset = asPositiveInteger(args.offset);
	const limit = asPositiveInteger(args.limit);
	if (offset === undefined && limit === undefined) return undefined;
	const start = offset ?? 1;
	if (limit === undefined) return `L${start}:-`;
	return `L${start}:L${start + limit - 1}`;
};

const buildReadCallText = (args: ReadArgs, theme: RenderTheme): string => {
	const rawPath = asString(args.path) ?? "...";
	const segments = [`${theme.fg("muted", "◎")} ${theme.fg("toolTitle", theme.bold("read"))} ${theme.fg("muted", rawPath)}`];
	const range = getReadRange(args);
	if (range) segments.push(range);
	return joinRenderSegments(segments, theme);
};

const buildReadResultText = (details: ReadDetails, theme: ColorTheme): string => {
	const truncation = details.truncation;
	if (!truncation?.truncated) return "";

	if (truncation.firstLineExceedsLimit) {
		return `  ${theme.fg("warning", `${formatSize(truncation.maxBytes ?? DEFAULT_MAX_BYTES)} limit`)}`;
	}
	if (truncation.truncatedBy === "lines") {
		return `  ${theme.fg("warning", `${truncation.maxLines ?? "?"} lines`)}`;
	}
	return `  ${theme.fg("warning", `${formatSize(truncation.maxBytes ?? DEFAULT_MAX_BYTES)} limit`)}`;
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
			const text = getReusableText(context.lastComponent);
			text.setText(buildReadCallText((args ?? {}) as ReadArgs, theme));
			return text;
		},
		renderResult(result, _options, theme, context) {
			const text = getReusableText(context.lastComponent);
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
