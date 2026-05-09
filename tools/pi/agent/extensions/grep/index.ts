import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import type { AgentToolResult, ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createGrepToolDefinition, DEFAULT_MAX_BYTES, formatSize, getAgentDir, truncateHead } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { getReusableText } from "../_shared/render-utils.js";
import { resolveSearchBinary } from "../_shared/search-binaries.js";
import { ensureToolActive, getFirstTextContent } from "../_shared/tool-utils.js";
import {
	balanceMatchesByFile,
	DEFAULT_LIMIT,
	DEFAULT_TIMEOUT_MS,
	type GrepOutputMode,
	normalizeLimit,
	normalizeOffset,
	normalizeOutputMode,
	normalizeSearchRoots,
	normalizeTimeout,
	resolveTypeFilter,
	type RawMatch,
} from "./logic.js";
import { formatMatches, GREP_MAX_LINE_LENGTH } from "./output.js";
import { type CountHit, type FileHit, runRipgrep, runRipgrepCounts, runRipgrepFiles } from "./ripgrep.js";
import { buildCollapsedResultText, formatGrepCall, type GrepRenderDetails } from "./render.js";

const MAX_INTERNAL_PROBE = 5_000;
const OUTPUT_LIMIT_LABEL = formatSize(DEFAULT_MAX_BYTES);
const OUTPUT_MODE_VALUES_LABEL = "content, files_with_matches, count";
const GREP_TOOL_DESCRIPTION = `Search file contents by pattern. Supports multipath roots, type filters, output modes (${OUTPUT_MODE_VALUES_LABEL}), pagination, timeout, ignored controls, literal mode. Output truncated to ${OUTPUT_LIMIT_LABEL}.`;
const GREP_PROMPT_SNIPPET = "Search file contents: output modes, pagination, type filters, ignored controls";

const PARAM_DESCRIPTIONS = {
	pattern: "Pattern: regex or literal string",
	paths: 'Search roots (default: ["."])',
	glob: "File glob filter, e.g. '*.ts' or '**/*.spec.ts'",
	type: "Language/file type filter, e.g. ts, js, py, rs",
	ignoreCase: "Case-insensitive search (default: false)",
	literal: "Treat pattern as literal, not regex (default: false)",
	context: "Context lines around matches (default: 0)",
	outputMode: `Output mode: ${OUTPUT_MODE_VALUES_LABEL} (default: content)`,
	ignored: "Include ignored files (default: false)",
	pcre2: "Enable ripgrep PCRE2 regex engine for look-around/backreferences (default: false)",
	offset: "Skip first N matches/results after ordering (default: 0)",
	limit: `Max matches/results returned (default: ${DEFAULT_LIMIT})`,
	timeoutMs: `Timeout ms (default: ${DEFAULT_TIMEOUT_MS})`,
} as const;

const grepSchema = Type.Object({
	pattern: Type.String({ description: PARAM_DESCRIPTIONS.pattern }),
	paths: Type.Optional(Type.Array(Type.String(), { description: PARAM_DESCRIPTIONS.paths, default: ["."] })),
	glob: Type.Optional(Type.String({ description: PARAM_DESCRIPTIONS.glob })),
	type: Type.Optional(Type.String({ description: PARAM_DESCRIPTIONS.type })),
	ignoreCase: Type.Optional(Type.Boolean({ description: PARAM_DESCRIPTIONS.ignoreCase, default: false })),
	literal: Type.Optional(Type.Boolean({ description: PARAM_DESCRIPTIONS.literal, default: false })),
	context: Type.Optional(Type.Number({ description: PARAM_DESCRIPTIONS.context, default: 0 })),
	outputMode: Type.Optional(Type.String({ description: PARAM_DESCRIPTIONS.outputMode, default: "content" })),
	ignored: Type.Optional(Type.Boolean({ description: PARAM_DESCRIPTIONS.ignored, default: false })),
	pcre2: Type.Optional(Type.Boolean({ description: PARAM_DESCRIPTIONS.pcre2, default: false })),
	offset: Type.Optional(Type.Number({ description: PARAM_DESCRIPTIONS.offset, default: 0 })),
	limit: Type.Optional(Type.Number({ description: PARAM_DESCRIPTIONS.limit, default: DEFAULT_LIMIT })),
	timeoutMs: Type.Optional(Type.Number({ description: PARAM_DESCRIPTIONS.timeoutMs, default: DEFAULT_TIMEOUT_MS })),
});

type GrepInput = {
	pattern: string;
	paths?: string[];
	glob?: string;
	type?: string;
	ignoreCase?: boolean;
	literal?: boolean;
	context?: number;
	outputMode?: string;
	ignored?: boolean;
	pcre2?: boolean;
	offset?: number;
	limit?: number;
	timeoutMs?: number;
};

const normalizeContext = (value: number | undefined): number | undefined => {
	if (value === undefined) return undefined;
	const normalized = Math.floor(value);
	if (!Number.isFinite(normalized) || normalized < 0) {
		throw new Error("context must be a non-negative number");
	}
	return normalized;
};

const hashLine = (line: string): string => createHash("sha1").update(line).digest("hex");

const isDirectoryPath = async (absolutePath: string): Promise<boolean> => {
	const stat = await fs.stat(absolutePath);
	return stat.isDirectory();
};

export const __test = {
	buildCollapsedResultText,
	formatGrepCall,
};

const formatOutputModeResult = async (
	matches: RawMatch[],
	outputMode: GrepOutputMode,
	contextLines: number,
): Promise<{ rawOutput: string; outputLineCount: number; linesTruncated: boolean }> => {
	if (outputMode === "files_with_matches") {
		const files = [...new Set(matches.map((match) => match.displayPath))];
		return { rawOutput: files.join("\n"), outputLineCount: files.length, linesTruncated: false };
	}
	if (outputMode === "count") {
		return { rawOutput: String(matches.length), outputLineCount: 1, linesTruncated: false };
	}
	const { output, linesTruncated } = await formatMatches(matches, contextLines);
	const outputLineCount = output.length === 0 ? 0 : output.split("\n").filter((line) => line.trim().length > 0).length;
	return { rawOutput: output, outputLineCount, linesTruncated };
};

const ensureRgViaNativeGrep = async (
	toolCallId: string,
	signal: AbortSignal,
	onUpdate: ((partial: AgentToolResult) => void) | undefined,
	cwd: string,
): Promise<void> => {
	const nativeGrep = createGrepToolDefinition(cwd);
	if (!nativeGrep.execute) throw new Error("native grep tool is unavailable");
	await nativeGrep.execute(
		toolCallId,
		{
			pattern: "__pi_search_binary_bootstrap_never_match__",
			path: path.join(getAgentDir(), "bin"),
			literal: true,
			limit: 1,
		},
		signal,
		onUpdate,
		{ cwd } as never,
	);
};

export default function grepExtension(pi: ExtensionAPI) {
	const activate = () => ensureToolActive(pi, "grep");
	pi.on("session_start", activate);
	pi.on("session_tree", activate);

	pi.registerTool({
		name: "grep",
		label: "grep",
		description: GREP_TOOL_DESCRIPTION,
		promptSnippet: GREP_PROMPT_SNIPPET,
		parameters: grepSchema,
		renderShell: "self",
		renderCall(args, theme, context) {
			const text = getReusableText(context.lastComponent);
			text.setText(formatGrepCall(args, theme));
			return text;
		},
		renderResult(result, _options, theme, context) {
			const text = getReusableText(context.lastComponent);
			const rawText = getFirstTextContent(result.content as Array<{ type: string; text?: string }>);

			if (context.isError) {
				text.setText(theme.fg("error", rawText.length > 0 ? rawText : "grep failed"));
				return text;
			}
			text.setText(buildCollapsedResultText(rawText, result.details as GrepRenderDetails | undefined, theme));
			return text;
		},
		async execute(toolCallId, input: GrepInput, signal, onUpdate, ctx) {
			if (!input.pattern || input.pattern.trim().length === 0) {
				throw new Error("pattern must be a non-empty string");
			}

			const effectiveLimit = normalizeLimit(input.limit);
			const effectiveOffset = normalizeOffset(input.offset);
			const requestedContext = normalizeContext(input.context);
			const outputMode = normalizeOutputMode(input.outputMode);
			const timeoutMs = normalizeTimeout(input.timeoutMs);
			const typeFilter = resolveTypeFilter(input.type);
			const useGitignore = input.ignored === true ? false : true;
			const roots = normalizeSearchRoots(input.paths);
			const requestedWindow = effectiveOffset + effectiveLimit + 1;
			const internalProbeLimit = Math.min(Math.max(requestedWindow * 5, requestedWindow), MAX_INTERNAL_PROBE);
			const cwd = ctx.cwd;
			const deadline = Date.now() + timeoutMs;
			let rgCommand = resolveSearchBinary("rg");
			if (!rgCommand) {
				await ensureRgViaNativeGrep(toolCallId, signal, onUpdate, cwd);
				rgCommand = resolveSearchBinary("rg");
				if (!rgCommand) throw new Error("rg is unavailable after native Pi ensureTool fallback");
			}
			if (outputMode === "files_with_matches") {
				const outputProbeLimit = MAX_INTERNAL_PROBE;
				const dedupeFiles = new Set<string>();
				const collectedFiles: FileHit[] = [];
				for (const root of roots) {
					if (collectedFiles.length >= outputProbeLimit) break;
					const remainingTimeoutMs = deadline - Date.now();
					if (remainingTimeoutMs <= 0) {
						throw new Error(`grep timed out after ${Math.max(1, Math.round(timeoutMs / 1000))}s`);
					}
					const absoluteRoot = path.resolve(cwd, root);
					try {
						await fs.stat(absoluteRoot);
					} catch {
						throw new Error(`Path not found: ${root}`);
					}
					const hits = await runRipgrepFiles({
						command: rgCommand,
						rootAbsolute: absoluteRoot,
						cwd,
						pattern: input.pattern,
						glob: input.glob,
						typeFilter,
						ignoreCase: input.ignoreCase === true,
						literal: input.literal === true,
						pcre2: input.pcre2 === true,
						useGitignore,
						maxResults: outputProbeLimit - collectedFiles.length,
						timeoutMs: remainingTimeoutMs,
						signal,
					});
					for (const hit of hits) {
						if (dedupeFiles.has(hit.displayPath)) continue;
						dedupeFiles.add(hit.displayPath);
						collectedFiles.push(hit);
						if (collectedFiles.length >= outputProbeLimit) break;
					}
				}
				const orderedFiles = [...collectedFiles].sort((a, b) => a.displayPath.localeCompare(b.displayPath));
				const pagedFiles = orderedFiles.slice(effectiveOffset, effectiveOffset + effectiveLimit + 1);
				const hasMoreFiles = pagedFiles.length > effectiveLimit;
				const selectedFiles = hasMoreFiles ? pagedFiles.slice(0, effectiveLimit) : pagedFiles;
				if (selectedFiles.length === 0) {
					return { content: [{ type: "text", text: "No matches found" }], details: undefined };
				}
				const rawOutput = selectedFiles.map((hit) => hit.displayPath).join("\n");
				const truncation = truncateHead(rawOutput, { maxLines: Number.MAX_SAFE_INTEGER, maxBytes: DEFAULT_MAX_BYTES });
				let output = truncation.content;
				const notices: string[] = [];
				const details: GrepRenderDetails = { outputMode, fileCount: selectedFiles.length, outputLineCount: selectedFiles.length };
				if (hasMoreFiles) {
					notices.push(`${effectiveLimit} results limit reached. Use offset=${effectiveOffset + effectiveLimit} for next page`);
					details.matchLimitReached = effectiveLimit;
				}
				if (truncation.truncated) {
					notices.push(`${formatSize(DEFAULT_MAX_BYTES)} output limit reached`);
					details.truncation = truncation;
				}
				if (notices.length > 0) output += `\n\n[${notices.join(". ")}]`;
				return { content: [{ type: "text", text: output }], details };
			}

			if (outputMode === "count") {
				const outputProbeLimit = MAX_INTERNAL_PROBE;
				const dedupeCounts = new Set<string>();
				const collectedCounts: CountHit[] = [];
				for (const root of roots) {
					if (collectedCounts.length >= outputProbeLimit) break;
					const remainingTimeoutMs = deadline - Date.now();
					if (remainingTimeoutMs <= 0) {
						throw new Error(`grep timed out after ${Math.max(1, Math.round(timeoutMs / 1000))}s`);
					}
					const absoluteRoot = path.resolve(cwd, root);
					try {
						await fs.stat(absoluteRoot);
					} catch {
						throw new Error(`Path not found: ${root}`);
					}
					const hits = await runRipgrepCounts({
						command: rgCommand,
						rootAbsolute: absoluteRoot,
						cwd,
						pattern: input.pattern,
						glob: input.glob,
						typeFilter,
						ignoreCase: input.ignoreCase === true,
						literal: input.literal === true,
						pcre2: input.pcre2 === true,
						useGitignore,
						maxResults: outputProbeLimit - collectedCounts.length,
						timeoutMs: remainingTimeoutMs,
						signal,
					});
					for (const hit of hits) {
						if (dedupeCounts.has(hit.displayPath)) continue;
						dedupeCounts.add(hit.displayPath);
						collectedCounts.push(hit);
						if (collectedCounts.length >= outputProbeLimit) break;
					}
				}
				const orderedCounts = [...collectedCounts].sort((a, b) => a.displayPath.localeCompare(b.displayPath));
				const pagedCounts = orderedCounts.slice(effectiveOffset, effectiveOffset + effectiveLimit + 1);
				const hasMoreCounts = pagedCounts.length > effectiveLimit;
				const selectedCounts = hasMoreCounts ? pagedCounts.slice(0, effectiveLimit) : pagedCounts;
				if (selectedCounts.length === 0) {
					return { content: [{ type: "text", text: "No matches found" }], details: undefined };
				}
				const totalCount = selectedCounts.reduce((sum, hit) => sum + hit.count, 0);
				const rawOutput = `${selectedCounts.map((hit) => `${hit.displayPath}:${hit.count}`).join("\n")}\n\nFound ${totalCount} total occurrence${totalCount === 1 ? "" : "s"} across ${selectedCounts.length} file${selectedCounts.length === 1 ? "" : "s"}.`;
				const truncation = truncateHead(rawOutput, { maxLines: Number.MAX_SAFE_INTEGER, maxBytes: DEFAULT_MAX_BYTES });
				let output = truncation.content;
				const notices: string[] = [];
				const details: GrepRenderDetails = { outputMode, matchCount: totalCount, fileCount: selectedCounts.length, outputLineCount: selectedCounts.length + 2 };
				if (hasMoreCounts) {
					notices.push(`${effectiveLimit} results limit reached. Use offset=${effectiveOffset + effectiveLimit} for next page`);
					details.matchLimitReached = effectiveLimit;
				}
				if (truncation.truncated) {
					notices.push(`${formatSize(DEFAULT_MAX_BYTES)} output limit reached`);
					details.truncation = truncation;
				}
				if (notices.length > 0) output += `\n\n[${notices.join(". ")}]`;
				return { content: [{ type: "text", text: output }], details };
			}

			const dedupe = new Set<string>();
			const collectedMatches: RawMatch[] = [];
			let hasDirectorySearch = false;

			for (const root of roots) {
				if (collectedMatches.length >= internalProbeLimit) break;
				const remainingTimeoutMs = deadline - Date.now();
				if (remainingTimeoutMs <= 0) {
					throw new Error(`grep timed out after ${Math.max(1, Math.round(timeoutMs / 1000))}s`);
				}
				const absoluteRoot = path.resolve(cwd, root);
				let directory = false;
				try {
					directory = await isDirectoryPath(absoluteRoot);
				} catch {
					throw new Error(`Path not found: ${root}`);
				}
				hasDirectorySearch ||= directory;
				const remaining = internalProbeLimit - collectedMatches.length;
				if (remaining <= 0) break;
				const matches = await runRipgrep({
					command: rgCommand,
					rootAbsolute: absoluteRoot,
					cwd,
					pattern: input.pattern,
					glob: input.glob,
					typeFilter,
					ignoreCase: input.ignoreCase === true,
					literal: input.literal === true,
					pcre2: input.pcre2 === true,
					useGitignore,
					maxMatches: remaining,
					timeoutMs: remainingTimeoutMs,
					signal,
				});
				for (const match of matches) {
					const key = `${match.absolutePath}:${match.lineNumber}:${hashLine(match.lineText)}`;
					if (dedupe.has(key)) continue;
					dedupe.add(key);
					collectedMatches.push(match);
					if (collectedMatches.length >= internalProbeLimit) break;
				}
			}

			const paged = collectedMatches.slice(effectiveOffset, effectiveOffset + effectiveLimit + 1);
			const hasMore = paged.length > effectiveLimit;
			const selectedWindow = hasMore ? paged.slice(0, effectiveLimit) : paged;
			const selected = hasDirectorySearch ? balanceMatchesByFile(selectedWindow) : selectedWindow;

			if (selected.length === 0) {
				return {
					content: [{ type: "text", text: "No matches found" }],
					details: undefined,
				};
			}

			const contextLines = outputMode === "content" ? (requestedContext ?? 0) : 0;
			const { rawOutput, outputLineCount, linesTruncated } = await formatOutputModeResult(selected, outputMode, contextLines);
			const truncation = truncateHead(rawOutput, {
				maxLines: Number.MAX_SAFE_INTEGER,
				maxBytes: DEFAULT_MAX_BYTES,
			});
			let output = truncation.content;
			const notices: string[] = [];
			const fileCount = new Set(selected.map((match) => match.displayPath)).size;
			const details: GrepRenderDetails = {
				outputMode,
				matchCount: selected.length,
				fileCount,
				outputLineCount,
			};

			if (hasMore) {
				notices.push(`${effectiveLimit} matches limit reached. Use offset=${effectiveOffset + effectiveLimit} for next page`);
				details.matchLimitReached = effectiveLimit;
			}
			if (truncation.truncated) {
				notices.push(`${formatSize(DEFAULT_MAX_BYTES)} output limit reached`);
				details.truncation = truncation;
			}
			if (linesTruncated) {
				notices.push(`Some lines truncated to ${GREP_MAX_LINE_LENGTH} chars`);
				details.linesTruncated = true;
			}
			if (notices.length > 0) {
				output += `\n\n[${notices.join(". ")}]`;
			}

			return {
				content: [{ type: "text", text: output }],
				details,
			};
		},
	});
}
