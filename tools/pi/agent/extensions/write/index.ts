import { existsSync } from "node:fs";
import path from "node:path";
import { createWriteToolDefinition, formatSize, keyHint, type ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";

type WriteArgs = {
	path?: unknown;
	file_path?: unknown;
	content?: unknown;
};

type WriteRenderState = {
	marker?: "+" | "~" | "?";
};

type ContentStats = {
	bytes: number;
	lines: number;
};

const asString = (value: unknown): string | undefined => (typeof value === "string" ? value : undefined);

const getContentStats = (content: string): ContentStats => {
	const bytes = Buffer.byteLength(content, "utf-8");
	if (content.length === 0) return { bytes, lines: 0 };

	let end = content.length;
	if (content.endsWith("\r\n")) {
		end -= 2;
	} else if (content.endsWith("\n")) {
		end -= 1;
	}
	if (end <= 0) return { bytes, lines: 0 };

	let lines = 1;
	for (let index = 0; index < end; index++) {
		if (content.charCodeAt(index) === 10) lines++;
	}
	return { bytes, lines };
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

const buildCollapsedWriteCallText = (
	args: WriteArgs,
	marker: "+" | "~" | "?",
	theme: { fg: (token: string, text: string) => string; bold: (text: string) => string },
): string => {
	const rawPath = asString(args.file_path) ?? asString(args.path) ?? "...";
	const content = asString(args.content) ?? "";
	const stats = getContentStats(content);
	const summary = `${formatSize(stats.bytes)} · ${stats.lines} ${stats.lines === 1 ? "line" : "lines"}`;

	return [
		`${theme.fg("toolTitle", theme.bold("write"))} ${theme.fg("accent", rawPath)}`,
		theme.fg("dim", `${marker} ${summary} (${keyHint("app.tools.expand", "to expand")})`),
	].join("\n");
};

export const __test = {
	getContentStats,
};

export default function writeExtension(pi: ExtensionAPI): void {
	const baseWrite = createWriteToolDefinition(process.cwd());

	pi.registerTool({
		...baseWrite,
		renderCall(args, theme, context) {
			if (context.expanded) {
				return baseWrite.renderCall
					? baseWrite.renderCall(args, theme, { ...context, lastComponent: undefined })
					: new Text("", 0, 0);
			}

			const state = context.state as WriteRenderState;
			const typedArgs = (args ?? {}) as WriteArgs;
			const rawPath = asString(typedArgs.file_path) ?? asString(typedArgs.path) ?? "...";
			if (!context.executionStarted) {
				state.marker = getWriteMarker(rawPath, context.cwd);
			} else if (state.marker === undefined) {
				state.marker = "?";
			}

			const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
			text.setText(buildCollapsedWriteCallText(typedArgs, state.marker ?? "?", theme));
			return text;
		},
	});
}
