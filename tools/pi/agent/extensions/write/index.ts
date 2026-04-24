import { existsSync } from "node:fs";
import path from "node:path";
import { createWriteToolDefinition, formatSize, type ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { getReusableText, joinRenderSegments, pluralize, type ColorTheme, type RenderTheme } from "../_shared/render-utils.js";
import { getUtf8ContentStats } from "../_shared/text-stats.js";
import { asString } from "../_shared/value-utils.js";

type WriteArgs = {
	path?: unknown;
	file_path?: unknown;
	content?: unknown;
};

type WriteRenderState = {
	marker?: "+" | "~" | "?";
};

const getWriteMarker = (rawPath: string, cwd: string): "+" | "~" | "?" => {
	if (rawPath.length === 0 || rawPath === "...") return "?";
	try {
		const absolutePath = path.isAbsolute(rawPath) ? rawPath : path.resolve(cwd, rawPath);
		return existsSync(absolutePath) ? "~" : "+";
	} catch {
		return "?";
	}
};

const formatWriteMarker = (marker: "+" | "~" | "?", theme: ColorTheme): string => {
	if (marker === "+") return theme.fg("toolDiffAdded", marker);
	if (marker === "~") return theme.fg("warning", marker);
	return theme.fg("muted", marker);
};

const buildCollapsedWriteCallText = (args: WriteArgs, marker: "+" | "~" | "?", theme: RenderTheme): string => {
	const rawPath = asString(args.file_path) ?? asString(args.path) ?? "...";
	const content = asString(args.content) ?? "";
	const stats = getUtf8ContentStats(content);
	const lines = `${stats.lines} ${pluralize(stats.lines, "line")}`;

	return joinRenderSegments(
		[
			`${theme.fg("muted", "▣")} ${theme.fg("toolTitle", theme.bold("write"))} ${formatWriteMarker(marker, theme)} ${theme.fg("muted", rawPath)}`,
			formatSize(stats.bytes),
			lines,
		],
		theme,
	);
};

export const __test = {
	buildCollapsedWriteCallText,
	formatWriteMarker,
	getContentStats: getUtf8ContentStats,
};

export default function writeExtension(pi: ExtensionAPI): void {
	const baseWrite = createWriteToolDefinition(process.cwd());

	pi.registerTool({
		...baseWrite,
		renderShell: "self",
		renderCall(args, theme, context) {
			const state = context.state as WriteRenderState;
			const typedArgs = (args ?? {}) as WriteArgs;
			const rawPath = asString(typedArgs.file_path) ?? asString(typedArgs.path) ?? "...";
			if (!context.executionStarted) {
				state.marker = getWriteMarker(rawPath, context.cwd);
			} else if (state.marker === undefined) {
				state.marker = "?";
			}

			const text = getReusableText(context.lastComponent);
			text.setText(buildCollapsedWriteCallText(typedArgs, state.marker ?? "?", theme));
			return text;
		},
	});
}
