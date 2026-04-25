import { createEditToolDefinition, type EditToolDetails, type ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { getReusableText, joinRenderSegments, pluralize, type ColorTheme, type RenderTheme } from "../_shared/render-utils.js";
import { countLogicalLines } from "../_shared/text-stats.js";
import { getFirstTextContent } from "../_shared/tool-utils.js";
import { asString } from "../_shared/value-utils.js";

type Edit = {
	oldText: string;
	newText: string;
};

type EditArgs = {
	path?: unknown;
	edits?: unknown;
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

const getRenderableEdits = (args: EditArgs): Edit[] | undefined => {
	if (!Array.isArray(args.edits)) return undefined;

	const edits = args.edits.filter(
		(edit): edit is Edit =>
			typeof edit === "object" &&
			edit !== null &&
			typeof (edit as { oldText?: unknown }).oldText === "string" &&
			typeof (edit as { newText?: unknown }).newText === "string",
	);
	if (edits.length === args.edits.length && edits.length > 0) return edits;

	return undefined;
};

const getLineStats = (edits: readonly Edit[]): LineStats =>
	edits.reduce<LineStats>(
		(stats, edit) => ({
			additions: stats.additions + countLogicalLines(edit.newText),
			removals: stats.removals + countLogicalLines(edit.oldText),
		}),
		{ additions: 0, removals: 0 },
	);

const formatLineStats = (stats: LineStats): string => `+${stats.additions}/-${stats.removals}`;

const formatColoredLineStats = (stats: LineStats, theme: ColorTheme): string =>
	`${theme.fg("toolDiffAdded", `+${stats.additions}`)}/${theme.fg("toolDiffRemoved", `-${stats.removals}`)}`;

const formatEditCount = (count: number): string => `${count} ${pluralize(count, "edit")}`;

const getEditSummary = (args: EditArgs, previous?: EditSummary): EditSummary => {
	const path = asString(args.path) ?? previous?.path ?? "...";
	const edits = getRenderableEdits(args);
	if (!edits) return { path, count: previous?.count, stats: previous?.stats };
	return { path, count: edits.length, stats: getLineStats(edits) };
};

const buildCollapsedEditCallText = (summary: EditSummary, theme: RenderTheme): string => {
	const segments = [`${theme.fg("muted", "✎")} ${theme.fg("toolTitle", theme.bold("edit"))} ${theme.fg("muted", summary.path)}`];

	if (summary.count !== undefined && summary.stats) {
		segments.push(formatEditCount(summary.count), formatColoredLineStats(summary.stats, theme));
	}

	return joinRenderSegments(segments, theme);
};

const getTextParts = (content: unknown): Array<{ type: string; text?: string }> => (Array.isArray(content) ? content : []);

export const __test = {
	buildCollapsedEditCallText,
	formatColoredLineStats,
	formatEditCount,
	formatLineStats,
	getEditSummary,
	getLineStats,
	getLogicalLineCount: countLogicalLines,
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
			const text = getReusableText(context.lastComponent);
			text.setText(buildCollapsedEditCallText(state.summary, theme));
			return text;
		},
		renderResult(result, _options, theme, context) {
			const text = getReusableText(context.lastComponent);
			if (context.isError) {
				text.setText(theme.fg("error", getFirstTextContent(getTextParts((result as RenderResult).content)) || "(no output)"));
				return text;
			}
			text.setText("");
			return text;
		},
	});
}
