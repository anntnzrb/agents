import { DEFAULT_MAX_BYTES, formatSize, type TruncationResult } from "@earendil-works/pi-coding-agent";
import { compactDisplayPath } from "../_shared/path-utils.js";
import { joinRenderSegments, pluralize, type ColorTheme, type RenderTheme } from "../_shared/render-utils.js";
import { summarizeList } from "../_shared/tool-utils.js";
import { GREP_MAX_LINE_LENGTH } from "./output.js";

type CallInput = {
	pattern: string;
	paths?: string[];
	glob?: string;
	type?: string;
	ignoreCase?: boolean;
	literal?: boolean;
	context?: number;
	outputMode?: string;
	ignored?: boolean;
	offset?: number;
	limit?: number;
	timeoutMs?: number;
};

export type GrepRenderDetails = {
	outputMode?: string;
	matchCount?: number;
	fileCount?: number;
	outputLineCount?: number;
	matchLimitReached?: number;
	truncation?: TruncationResult;
	linesTruncated?: boolean;
};

const stripNoticeSuffix = (text: string): string => text.replace(/\n\n\[[^\n]+\]$/, "");

const RENDER_LABELS = {
	filesOutputMode: "files",
	ignoreCase: "i",
	ignoredOn: "ignored",
	offset: "offset",
	limit: "limit",
} as const;

const formatOutputMode = (value: string): string => {
	if (value === "files_with_matches") return RENDER_LABELS.filesOutputMode;
	return value;
};

const summarizeOutput = (output: string): { matchCount: number; fileCount: number; lineCount: number } => {
	let matchCount = 0;
	const files = new Set<string>();
	const lines = output.split("\n").filter((line) => line.trim().length > 0);
	for (const line of lines) {
		const match = /^(.*):(\d+): /.exec(line);
		if (!match) continue;
		matchCount += 1;
		const filePath = match[1];
		if (filePath) files.add(filePath);
	}
	return { matchCount, fileCount: files.size, lineCount: lines.length };
};

export const formatGrepCall = (input: CallInput, theme: RenderTheme): string => {
	const pattern = typeof input.pattern === "string" ? input.pattern : "";
	const pathRoots = input.paths?.filter((entry) => typeof entry === "string" && entry.trim().length > 0) ?? [];
	const displayRoots = pathRoots.map((entry) => compactDisplayPath(entry));
	const scope = pathRoots.length > 0 ? `paths:${summarizeList(displayRoots)}` : ".";
	const flags: string[] = [theme.fg("accent", `/${pattern}/`)];
	if (input.glob) flags.push(theme.fg("muted", input.glob));
	if (input.type) flags.push(theme.fg("muted", input.type));
	if (input.outputMode && input.outputMode !== "content") flags.push(theme.fg("accent", formatOutputMode(input.outputMode)));
	if (input.literal) flags.push(theme.fg("muted", "literal"));
	if (input.ignoreCase) flags.push(theme.fg("muted", RENDER_LABELS.ignoreCase));
	if (input.context !== undefined) flags.push(theme.fg("muted", `ctx ${input.context}`));
	if (input.ignored) flags.push(theme.fg("warning", RENDER_LABELS.ignoredOn));
	if ((input.offset ?? 0) > 0) flags.push(theme.fg("muted", `${RENDER_LABELS.offset}:${input.offset}`));
	if (input.limit !== undefined) flags.push(theme.fg("muted", `${RENDER_LABELS.limit}:${input.limit}`));
	if (input.timeoutMs !== undefined) flags.push(theme.fg("muted", `${input.timeoutMs}ms`));

	return joinRenderSegments([`${theme.fg("muted", "⌕")} ${theme.fg("toolTitle", theme.bold("grep"))} ${theme.fg("muted", scope)}`, ...flags], theme);
};

export const buildCollapsedResultText = (
	rawText: string,
	details: GrepRenderDetails | undefined,
	theme: ColorTheme,
): string => {
	const body = stripNoticeSuffix(rawText).trim();
	if (body.length === 0) return "  0 matches";
	if (body === "No matches found") return "  0 matches";

	const lines: string[] = [];
	const matchCount = details?.matchCount;
	const fileCount = details?.fileCount;
	if (details?.outputMode === "files_with_matches" && typeof fileCount === "number") {
		lines.push(`↳ ${fileCount} ${pluralize(fileCount, "file")}`);
	} else if (typeof matchCount === "number" && typeof fileCount === "number") {
		const prefix = details?.outputMode === "count" ? "Σ" : "↳";
		lines.push(`${prefix} ${matchCount} ${pluralize(matchCount, "match", "matches")} in ${fileCount} ${pluralize(fileCount, "file")}`);
	} else {
		const fallback = summarizeOutput(body);
		if (fallback.matchCount > 0) {
			lines.push(`↳ ${fallback.matchCount} ${pluralize(fallback.matchCount, "match", "matches")} in ${fallback.fileCount} ${pluralize(fallback.fileCount, "file")}`);
		} else {
			const lineCount = details?.outputLineCount ?? fallback.lineCount;
			lines.push(`${lineCount} ${pluralize(lineCount, "line")} of output`);
		}
	}

	const notices: string[] = [];
	if (details?.truncation?.truncated) notices.push(`${formatSize(DEFAULT_MAX_BYTES)} output limit`);
	if (details?.linesTruncated) notices.push(`line max ${GREP_MAX_LINE_LENGTH}`);
	if (notices.length > 0) lines.push(theme.fg("warning", notices.join(" · ")));
	return `  ${joinRenderSegments(lines, theme)}`;
};
