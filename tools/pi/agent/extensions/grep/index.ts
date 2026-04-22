import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { DEFAULT_MAX_BYTES, formatSize, truncateHead } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";
import { Type } from "@sinclair/typebox";
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

const MAX_INTERNAL_PROBE = 5_000;
const GREP_MAX_LINE_LENGTH = 500;

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

const ensureToolActive = (pi: ExtensionAPI, toolName: string): void => {
	const nextTools = new Set(pi.getActiveTools());
	if (nextTools.has(toolName)) return;
	nextTools.add(toolName);
	pi.setActiveTools(Array.from(nextTools));
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

const truncateLineForOutput = (line: string): { text: string; truncated: boolean } => {
	if (line.length <= GREP_MAX_LINE_LENGTH) return { text: line, truncated: false };
	return {
		text: `${line.slice(0, GREP_MAX_LINE_LENGTH)}... [truncated]`,
		truncated: true,
	};
};

const summarizeList = (items: string[], max = 2): string => {
	if (items.length <= max) return items.join(", ");
	return `${items.slice(0, max).join(", ")} +${items.length - max} more`;
};

const formatGrepCall = (input: GrepInput, theme: { fg: (token: string, text: string) => string; bold: (text: string) => string }): string => {
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

	return await new Promise<RawMatch[]>((resolve, reject) => {
		const child = spawn("rg", args, { stdio: ["ignore", "pipe", "pipe"] });
		const lines = createInterface({ input: child.stdout });
		const matches: RawMatch[] = [];
		let stderr = "";
		let aborted = false;
		let killedForCap = false;

		const stopChild = (forCap = false) => {
			if (!child.killed) {
				killedForCap = forCap;
				child.kill();
			}
		};

		const cleanup = () => {
			lines.close();
			signal?.removeEventListener("abort", onAbort);
		};

		const onAbort = () => {
			aborted = true;
			stopChild();
		};
		signal?.addEventListener("abort", onAbort, { once: true });

		child.stderr.on("data", (chunk) => {
			stderr += chunk.toString();
		});

		lines.on("line", (line) => {
			if (matches.length >= maxMatches) {
				stopChild(true);
				return;
			}
			const event = parseMatchEvent(line);
			if (!event || event.type !== "match") return;
			const filePath = event.data?.path?.text;
			const lineNumber = event.data?.line_number;
			const lineText = event.data?.lines?.text;
			if (!filePath || typeof lineNumber !== "number") return;
			const absolutePath = path.isAbsolute(filePath) ? filePath : path.resolve(rootAbsolute, filePath);
			const cleanedLine = (lineText ?? "").replace(/\r\n/g, "\n").replace(/\r/g, "").replace(/\n$/, "");
			const displayPath = toPosixRelative(cwd, absolutePath);
			matches.push({
				absolutePath,
				displayPath,
				lineNumber,
				lineText: cleanedLine,
			});
			if (matches.length >= maxMatches) {
				stopChild(true);
			}
		});

		child.on("error", (error) => {
			cleanup();
			if ((error as NodeJS.ErrnoException).code === "ENOENT") {
				reject(new Error(toolMissingMessage("rg", "ripgrep (e.g. `brew install ripgrep`)")));
				return;
			}
			reject(new Error(`Failed to run ripgrep: ${error.message}`));
		});

		child.on("close", (code) => {
			cleanup();
			if (aborted) {
				reject(new Error("Operation aborted"));
				return;
			}
			if (!killedForCap && code !== 0 && code !== 1) {
				const detail = stderr.trim() || `ripgrep exited with code ${code}`;
				reject(new Error(detail));
				return;
			}
			resolve(matches);
		});
	});
};

const readFileLinesCached = async (cache: Map<string, string[]>, absolutePath: string): Promise<string[]> => {
	const existing = cache.get(absolutePath);
	if (existing) return existing;
	try {
		const content = await fs.readFile(absolutePath, "utf8");
		const lines = content.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
		cache.set(absolutePath, lines);
		return lines;
	} catch {
		cache.set(absolutePath, []);
		return [];
	}
};

const formatMatches = async (matches: RawMatch[], contextLines: number): Promise<{ output: string; linesTruncated: boolean }> => {
	if (matches.length === 0) return { output: "", linesTruncated: false };
	let linesTruncated = false;
	const outputLines: string[] = [];
	const fileCache = new Map<string, string[]>();

	if (contextLines <= 0) {
		for (const match of matches) {
			const { text, truncated } = truncateLineForOutput(match.lineText);
			if (truncated) linesTruncated = true;
			outputLines.push(`${match.displayPath}:${match.lineNumber}: ${text}`);
		}
		return { output: outputLines.join("\n"), linesTruncated };
	}

	for (const match of matches) {
		const lines = await readFileLinesCached(fileCache, match.absolutePath);
		if (lines.length === 0) {
			outputLines.push(`${match.displayPath}:${match.lineNumber}: (unable to read file)`);
			continue;
		}
		const start = Math.max(1, match.lineNumber - contextLines);
		const end = Math.min(lines.length, match.lineNumber + contextLines);
		for (let lineNumber = start; lineNumber <= end; lineNumber += 1) {
			const lineText = lines[lineNumber - 1] ?? "";
			const { text, truncated } = truncateLineForOutput(lineText);
			if (truncated) linesTruncated = true;
			if (lineNumber === match.lineNumber) {
				outputLines.push(`${match.displayPath}:${lineNumber}: ${text}`);
			} else {
				outputLines.push(`${match.displayPath}-${lineNumber}- ${text}`);
			}
		}
	}

	return { output: outputLines.join("\n"), linesTruncated };
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
		renderCall(args, theme, context) {
			const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
			text.setText(formatGrepCall(args, theme));
			return text;
		},
		async execute(_toolCallId, input: GrepInput, signal, _onUpdate, ctx) {
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
			const details: {
				matchLimitReached?: number;
				truncation?: ReturnType<typeof truncateHead>;
				linesTruncated?: boolean;
			} = {};

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
				details: Object.keys(details).length > 0 ? details : undefined,
			};
		},
	});
}
