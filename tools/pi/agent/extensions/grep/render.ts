import { DEFAULT_MAX_BYTES, formatSize, keyHint, type TruncationResult } from "@mariozechner/pi-coding-agent";
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
	gitignore?: boolean;
	noIgnore?: boolean;
	offset?: number;
	limit?: number;
};

export type GrepRenderDetails = {
	matchCount?: number;
	fileCount?: number;
	outputLineCount?: number;
	matchLimitReached?: number;
	truncation?: TruncationResult;
	linesTruncated?: boolean;
};

const stripNoticeSuffix = (text: string): string => text.replace(/\n\n\[[^\n]+\]$/, "");

const pluralize = (count: number, singular: string, plural: string): string =>
	count === 1 ? singular : plural;

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
	const scope = pathRoots.length > 0 ? `paths:${summarizeList(pathRoots)}` : `path:${input.path ?? "."}`;
	const flags: string[] = [];
	if (input.type) flags.push(`type:${input.type}`);
	if (input.glob) flags.push(`glob:${input.glob}`);
	if (input.literal) flags.push("literal");
	if (input.ignoreCase) flags.push("ignoreCase");
	if (input.context !== undefined) flags.push(`ctx:${input.context}`);
	if (input.gitignore === false) flags.push("gitignore:false");
	if (input.noIgnore) flags.push("noIgnore");
	if ((input.offset ?? 0) > 0) flags.push(`offset:${input.offset}`);
	if (input.limit !== undefined) flags.push(`limit:${input.limit}`);

	let line =
		theme.fg("toolTitle", theme.bold("grep")) +
		" " +
		theme.fg("accent", `/${pattern}/`) +
		theme.fg("toolOutput", ` in ${scope}`);
	if (flags.length > 0) {
		line += theme.fg("muted", ` [${flags.join(", ")}]`);
	}
	return line;
};

export const buildCollapsedResultText = (
	rawText: string,
	details: GrepRenderDetails | undefined,
	theme: { fg: (token: string, text: string) => string },
): string => {
	const body = stripNoticeSuffix(rawText).trim();
	if (body.length === 0) return theme.fg("dim", "(no output)");
	if (body === "No matches found") return theme.fg("dim", body);

	const lines: string[] = [];
	const matchCount = details?.matchCount;
	const fileCount = details?.fileCount;
	if (typeof matchCount === "number" && typeof fileCount === "number") {
		lines.push(
			theme.fg(
				"toolOutput",
				`${matchCount} ${pluralize(matchCount, "match", "matches")} · ${fileCount} ${pluralize(fileCount, "file", "files")}`,
			),
		);
	} else {
		const fallback = summarizeOutput(body);
		if (fallback.matchCount > 0) {
			lines.push(
				theme.fg(
					"toolOutput",
					`${fallback.matchCount} ${pluralize(fallback.matchCount, "match", "matches")} · ${fallback.fileCount} ${pluralize(fallback.fileCount, "file", "files")}`,
				),
			);
		} else {
			const lineCount = details?.outputLineCount ?? fallback.lineCount;
			lines.push(theme.fg("toolOutput", `${lineCount} ${pluralize(lineCount, "line", "lines")} of output`));
		}
	}

	const notices: string[] = [];
	if (details?.truncation?.truncated) {
		notices.push(`${formatSize(DEFAULT_MAX_BYTES)} output limit`);
	}
	if (details?.linesTruncated) {
		notices.push(`line max ${GREP_MAX_LINE_LENGTH}`);
	}
	if (notices.length > 0) {
		lines.push(theme.fg("warning", notices.join(" · ")));
	}
	lines.push(theme.fg("dim", `(${keyHint("app.tools.expand", "to expand")})`));
	return lines.join("\n");
};
