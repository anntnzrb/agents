import { DEFAULT_MAX_BYTES, formatSize, type TruncationResult } from "@mariozechner/pi-coding-agent";
import { summarizeList } from "../_shared/tool-utils.js";
import { GREP_MAX_LINE_LENGTH } from "./output.js";

type Theme = {
	fg: (token: string, text: string) => string;
	bold: (text: string) => string;
};

type CallInput = {
	pattern: string;
	path?: string;
	paths?: string[];
	glob?: string;
	type?: string;
	ignoreCase?: boolean;
	literal?: boolean;
	context?: number;
	outputMode?: string;
	gitignore?: boolean;
	noIgnore?: boolean;
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
	gitignoreOff: "gitignore off",
	ignoredOn: "ignored on",
	offset: "offset",
	limit: "limit",
} as const;

const pluralize = (count: number, singular: string, plural: string): string => (count === 1 ? singular : plural);

const compactPath = (value: string): string => {
	if (value === "." || value.startsWith("paths:")) return value;
	const normalized = value.replace(/\\/g, "/");
	const parts = normalized.split("/").filter(Boolean);
	if (parts.length <= 4) return value;
	const prefix = normalized.startsWith("/") ? "…/" : "…/";
	return `${prefix}${parts.slice(-4).join("/")}`;
};

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

export const formatGrepCall = (input: CallInput, theme: Theme): string => {
	const pattern = typeof input.pattern === "string" ? input.pattern : "";
	const pathRoots = input.paths?.filter((entry) => typeof entry === "string" && entry.trim().length > 0) ?? [];
	const scope = compactPath(pathRoots.length > 0 ? `paths:${summarizeList(pathRoots)}` : (input.path ?? "."));
	const flags: string[] = [theme.fg("accent", `/${pattern}/`)];
	if (input.glob) flags.push(theme.fg("muted", input.glob));
	if (input.type) flags.push(theme.fg("muted", input.type));
	if (input.outputMode && input.outputMode !== "content") flags.push(theme.fg("accent", formatOutputMode(input.outputMode)));
	if (input.literal) flags.push(theme.fg("muted", "literal"));
	if (input.ignoreCase) flags.push(theme.fg("muted", RENDER_LABELS.ignoreCase));
	if (input.context !== undefined) flags.push(theme.fg("muted", `ctx ${input.context}`));
	if (input.gitignore === false) flags.push(theme.fg("warning", RENDER_LABELS.gitignoreOff));
	if (input.noIgnore) flags.push(theme.fg("warning", RENDER_LABELS.ignoredOn));
	if ((input.offset ?? 0) > 0) flags.push(theme.fg("muted", `${RENDER_LABELS.offset}:${input.offset}`));
	if (input.limit !== undefined) flags.push(theme.fg("muted", `${RENDER_LABELS.limit}:${input.limit}`));
	if (input.timeoutMs !== undefined) flags.push(theme.fg("muted", `${input.timeoutMs}ms`));

	return [`${theme.fg("muted", "⌕")} ${theme.fg("toolTitle", theme.bold("grep"))} ${theme.fg("muted", scope)}`, ...flags].join(
		theme.fg("dim", " · "),
	);
};

export const buildCollapsedResultText = (
	rawText: string,
	details: GrepRenderDetails | undefined,
	theme: { fg: (token: string, text: string) => string },
): string => {
	const body = stripNoticeSuffix(rawText).trim();
	if (body.length === 0) return "  0 matches";
	if (body === "No matches found") return "  0 matches";

	const lines: string[] = [];
	const matchCount = details?.matchCount;
	const fileCount = details?.fileCount;
	if (details?.outputMode === "files_with_matches" && typeof fileCount === "number") {
		lines.push(`↳ ${fileCount} ${pluralize(fileCount, "file", "files")}`);
	} else if (typeof matchCount === "number" && typeof fileCount === "number") {
		const prefix = details?.outputMode === "count" ? "Σ" : "↳";
		lines.push(`${prefix} ${matchCount} ${pluralize(matchCount, "match", "matches")} in ${fileCount} ${pluralize(fileCount, "file", "files")}`);
	} else {
		const fallback = summarizeOutput(body);
		if (fallback.matchCount > 0) {
			lines.push(`↳ ${fallback.matchCount} ${pluralize(fallback.matchCount, "match", "matches")} in ${fallback.fileCount} ${pluralize(fallback.fileCount, "file", "files")}`);
		} else {
			const lineCount = details?.outputLineCount ?? fallback.lineCount;
			lines.push(`${lineCount} ${pluralize(lineCount, "line", "lines")} of output`);
		}
	}

	const notices: string[] = [];
	if (details?.truncation?.truncated) notices.push(`${formatSize(DEFAULT_MAX_BYTES)} output limit`);
	if (details?.linesTruncated) notices.push(`line max ${GREP_MAX_LINE_LENGTH}`);
	if (notices.length > 0) lines.push(theme.fg("warning", notices.join(" · ")));
	return `  ${lines.join(theme.fg("dim", " · "))}`;
};
