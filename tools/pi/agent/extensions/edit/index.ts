import { createEditToolDefinition, type EditToolDetails, type ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";
import { getFirstTextContent } from "../_shared/tool-utils.js";

type Edit = {
	oldText: string;
	newText: string;
};

type EditArgs = {
	path?: unknown;
	file_path?: unknown;
	edits?: unknown;
	oldText?: unknown;
	newText?: unknown;
};

type LineStats = {
	additions: number;
	removals: number;
};

type EditSummary = {
	path: string;
	count: number | undefined;
	stats: LineStats | undefined;
};

type EditRenderState = {
	summary?: EditSummary;
};

type RenderResult = {
	content?: unknown;
	details?: EditToolDetails;
};

const asString = (value: unknown): string | undefined => (typeof value === "string" ? value : undefined);

const getLogicalLineCount = (content: string): number => {
	if (content.length === 0) return 0;

	let end = content.length;
	if (content.endsWith("\r\n")) {
		end -= 2;
	} else if (content.endsWith("\n")) {
		end -= 1;
	}
	if (end <= 0) return 0;

	let lines = 1;
	for (let index = 0; index < end; index++) {
		if (content.charCodeAt(index) === 10) lines++;
	}
	return lines;
};

const parseEditsString = (value: string): Edit[] | undefined => {
	try {
		const parsed = JSON.parse(value) as unknown;
		return getRenderableEdits({ edits: parsed });
	} catch {
		return undefined;
	}
};

const getRenderableEdits = (args: EditArgs): Edit[] | undefined => {
	if (Array.isArray(args.edits)) {
		const edits = args.edits.filter(
			(edit): edit is Edit =>
				typeof edit === "object" &&
				edit !== null &&
				typeof (edit as { oldText?: unknown }).oldText === "string" &&
				typeof (edit as { newText?: unknown }).newText === "string",
		);
		if (edits.length === args.edits.length && edits.length > 0) return edits;
	}

	if (typeof args.edits === "string") {
		const edits = parseEditsString(args.edits);
		if (edits) return edits;
	}

	if (typeof args.oldText === "string" && typeof args.newText === "string") {
		return [{ oldText: args.oldText, newText: args.newText }];
	}

	return undefined;
};

const getLineStats = (edits: readonly Edit[]): LineStats =>
	edits.reduce<LineStats>(
		(stats, edit) => ({
			additions: stats.additions + getLogicalLineCount(edit.newText),
			removals: stats.removals + getLogicalLineCount(edit.oldText),
		}),
		{ additions: 0, removals: 0 },
	);

const formatLineStats = (stats: LineStats): string => `+${stats.additions}/-${stats.removals}`;

const formatColoredLineStats = (stats: LineStats, theme: { fg: (token: string, text: string) => string }): string =>
	`${theme.fg("toolDiffAdded", `+${stats.additions}`)}/${theme.fg("toolDiffRemoved", `-${stats.removals}`)}`;

const formatEditCount = (count: number): string => `${count} ${count === 1 ? "edit" : "edits"}`;

const getEditSummary = (args: EditArgs, previous?: EditSummary): EditSummary => {
	const path = asString(args.path) ?? asString(args.file_path) ?? previous?.path ?? "...";
	const edits = getRenderableEdits(args);
	if (!edits) return { path, count: previous?.count, stats: previous?.stats };
	return { path, count: edits.length, stats: getLineStats(edits) };
};

const buildCollapsedEditCallText = (
	summary: EditSummary,
	theme: { fg: (token: string, text: string) => string; bold: (text: string) => string },
): string => {
	const segments = [`${theme.fg("muted", "✎")} ${theme.fg("toolTitle", theme.bold("edit"))} ${theme.fg("muted", summary.path)}`];

	if (summary.count !== undefined && summary.stats) {
		segments.push(formatEditCount(summary.count), formatColoredLineStats(summary.stats, theme));
	}

	return segments.join(theme.fg("dim", " · "));
};

const getTextParts = (content: unknown): Array<{ type: string; text?: string }> => (Array.isArray(content) ? content : []);

export const __test = {
	buildCollapsedEditCallText,
	formatColoredLineStats,
	formatEditCount,
	formatLineStats,
	getEditSummary,
	getLineStats,
	getLogicalLineCount,
	getRenderableEdits,
};

export default function editExtension(pi: ExtensionAPI): void {
	const baseEdit = createEditToolDefinition(process.cwd());

	pi.registerTool({
		...baseEdit,
		renderShell: "self",
		renderCall(args, theme, context) {
			const state = context.state as EditRenderState;
			state.summary = getEditSummary((args ?? {}) as EditArgs, state.summary);
			const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
			text.setText(buildCollapsedEditCallText(state.summary, theme));
			return text;
		},
		renderResult(result, _options, theme, context) {
			const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
			if (context.isError) {
				text.setText(theme.fg("error", getFirstTextContent(getTextParts((result as RenderResult).content)) || "(no output)"));
				return text;
			}
			text.setText("");
			return text;
		},
	});
}
