import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import type { AgentToolResult, ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { createGrepToolDefinition, DEFAULT_MAX_BYTES, formatSize, getAgentDir, truncateHead } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";
import { Type } from "@sinclair/typebox";
import { runLineStreamingProcess } from "../_shared/line-process.js";
import { resolveSearchBinary } from "../_shared/search-binaries.js";
import { ensureToolActive, getFirstTextContent } from "../_shared/tool-utils.js";
import {
	balanceMatchesByFile,
	normalizeLimit,
	normalizeOffset,
	normalizeSearchRoots,
	resolveTypeFilter,
	toPosixRelative,
	type RawMatch,
	type TypeFilter,
} from "./logic.js";
import { formatMatches, GREP_MAX_LINE_LENGTH } from "./output.js";
import { buildCollapsedResultText, formatGrepCall, type GrepRenderDetails } from "./render.js";

const MAX_INTERNAL_PROBE = 5_000;

type MatchEvent = {
	type?: string;
	data?: {
		path?: { text?: string };
		line_number?: number;
		lines?: { text?: string };
	};
};
const grepSchema = Type.Object({
	pattern: Type.String({ description: "Search pattern (regex or literal string)" }),
	path: Type.Optional(Type.String({ description: "Directory or file to search (default: current directory)" })),
	paths: Type.Optional(Type.Array(Type.String({ description: "Search roots. Mutually exclusive with path." }))),
	glob: Type.Optional(Type.String({ description: "Filter files by glob pattern, e.g. '*.ts' or '**/*.spec.ts'" })),
	type: Type.Optional(Type.String({ description: "Language/file type filter, e.g. ts, js, py, rs" })),
	ignoreCase: Type.Optional(Type.Boolean({ description: "Case-insensitive search (default: false)" })),
	literal: Type.Optional(Type.Boolean({ description: "Treat pattern as literal string instead of regex (default: false)" })),
	context: Type.Optional(Type.Number({ description: "Number of context lines around matches" })),
	gitignore: Type.Optional(Type.Boolean({ description: "Respect .gitignore (default: true)" })),
	noIgnore: Type.Optional(Type.Boolean({ description: "Include ignored files (overrides gitignore)" })),
	offset: Type.Optional(Type.Number({ description: "Skip first N matches after ordering (default: 0)" })),
	limit: Type.Optional(Type.Number({ description: "Maximum number of matches to return (default: 100)" })),
});

type GrepInput = {
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

const normalizeContext = (value: number | undefined): number | undefined => {
	if (value === undefined) return undefined;
	const normalized = Math.floor(value);
	if (!Number.isFinite(normalized) || normalized < 0) {
		throw new Error("context must be a non-negative number");
	}
	return normalized;
};

const hashLine = (line: string): string => createHash("sha1").update(line).digest("hex");

const parseMatchEvent = (line: string): MatchEvent | null => {
	if (line.trim().length === 0) return null;
	try {
		return JSON.parse(line) as MatchEvent;
	} catch {
		return null;
	}
};

const toolMissingMessage = (binary: string, installHint: string): string =>
	`'${binary}' is not available in PATH. Install ${installHint} and retry.`;

const isDirectoryPath = async (absolutePath: string): Promise<boolean> => {
	const stat = await fs.stat(absolutePath);
	return stat.isDirectory();
};

const runRipgrep = async (params: {
	command: string;
	rootAbsolute: string;
	cwd: string;
	pattern: string;
	glob: string | undefined;
	typeFilter: TypeFilter | null;
	ignoreCase: boolean;
	literal: boolean;
	useGitignore: boolean;
	maxMatches: number;
	signal?: AbortSignal;
}): Promise<RawMatch[]> => {
	const {
		command,
		rootAbsolute,
		cwd,
		pattern,
		glob,
		typeFilter,
		ignoreCase,
		literal,
		useGitignore,
		maxMatches,
		signal,
	} = params;
	const args = ["--json", "--line-number", "--color=never", "--hidden"];
	if (ignoreCase) args.push("--ignore-case");
	if (literal) args.push("--fixed-strings");
	if (!useGitignore) args.push("--no-ignore");
	if (glob) args.push("--glob", glob);
	if (typeFilter) {
		for (const typeGlob of typeFilter.rgGlobs) {
			args.push("--glob", typeGlob);
		}
	}
	args.push(pattern, rootAbsolute);

	return await runLineStreamingProcess<RawMatch>({
		command,
		args,
		maxResults: maxMatches,
		...(signal ? { signal } : {}),
		missingBinaryMessage: toolMissingMessage("rg", "ripgrep (e.g. `brew install ripgrep`)"),
		runErrorLabel: "ripgrep",
		exitErrorLabel: "ripgrep",
		parseLine: (line) => {
			const event = parseMatchEvent(line);
			if (!event || event.type !== "match") return undefined;
			const filePath = event.data?.path?.text;
			const lineNumber = event.data?.line_number;
			const lineText = event.data?.lines?.text;
			if (!filePath || typeof lineNumber !== "number") return undefined;
			const absolutePath = path.isAbsolute(filePath) ? filePath : path.resolve(rootAbsolute, filePath);
			const cleanedLine = (lineText ?? "").replace(/\r\n/g, "\n").replace(/\r/g, "").replace(/\n$/, "");
			const displayPath = toPosixRelative(cwd, absolutePath);
			return {
				absolutePath,
				displayPath,
				lineNumber,
				lineText: cleanedLine,
			};
		},
	});
};

export const __test = {
	buildCollapsedResultText,
	formatGrepCall,
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
		description:
			"Search file contents for a pattern with optional multipath, type filtering, pagination, and gitignore/literal controls. Output is truncated to 50KB.",
		promptSnippet: "Search file contents for patterns with pagination and type filtering",
		parameters: grepSchema,
		renderShell: "self",
		renderCall(args, theme, context) {
			const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
			text.setText(formatGrepCall(args, theme));
			return text;
		},
		renderResult(result, _options, theme, context) {
			const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
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
			const typeFilter = resolveTypeFilter(input.type);
			const useGitignore = input.noIgnore === true ? false : input.gitignore !== false;
			const roots = normalizeSearchRoots(input.path, input.paths);
			const requestedWindow = effectiveOffset + effectiveLimit + 1;
			const internalProbeLimit = Math.min(Math.max(requestedWindow * 5, requestedWindow), MAX_INTERNAL_PROBE);
			const cwd = ctx.cwd;
			let rgCommand = resolveSearchBinary("rg");
			if (!rgCommand) {
				await ensureRgViaNativeGrep(toolCallId, signal, onUpdate, cwd);
				rgCommand = resolveSearchBinary("rg");
				if (!rgCommand) throw new Error("rg is unavailable after native Pi ensureTool fallback");
			}
			const dedupe = new Set<string>();
			const collectedMatches: RawMatch[] = [];
			let hasDirectorySearch = false;

			for (const root of roots) {
				if (collectedMatches.length >= internalProbeLimit) break;
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
					useGitignore,
					maxMatches: remaining,
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

			const orderedMatches = hasDirectorySearch ? balanceMatchesByFile(collectedMatches) : collectedMatches;
			const paged = orderedMatches.slice(effectiveOffset, effectiveOffset + effectiveLimit + 1);
			const hasMore = paged.length > effectiveLimit;
			const selected = hasMore ? paged.slice(0, effectiveLimit) : paged;

			if (selected.length === 0) {
				return {
					content: [{ type: "text", text: "No matches found" }],
					details: undefined,
				};
			}

			const contextLines = requestedContext ?? 0;
			const { output: rawOutput, linesTruncated } = await formatMatches(selected, contextLines);
			const truncation = truncateHead(rawOutput, {
				maxLines: Number.MAX_SAFE_INTEGER,
				maxBytes: DEFAULT_MAX_BYTES,
			});
			let output = truncation.content;
			const notices: string[] = [];
			const fileCount = new Set(selected.map((match) => match.displayPath)).size;
			const outputLineCount = rawOutput.length === 0 ? 0 : rawOutput.split("\n").filter((line) => line.trim().length > 0).length;
			const details: GrepRenderDetails = {
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
