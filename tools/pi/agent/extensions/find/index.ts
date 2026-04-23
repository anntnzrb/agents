import { promises as fs } from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { DEFAULT_MAX_BYTES, formatSize, keyHint, truncateHead } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";
import { Type } from "@sinclair/typebox";
import { runLineStreamingProcess } from "../_shared/line-process.js";
import { ensureToolActive, getFirstTextContent, summarizeList } from "../_shared/tool-utils.js";
import { buildFdArgs, normalizeLimit, normalizeSearchRoots, normalizeTimeout } from "./logic.js";

const findSchema = Type.Object({
	pattern: Type.String({ description: "Glob pattern to match files, e.g. '*.ts', '**/*.json', or 'src/**/*.spec.ts'" }),
	path: Type.Optional(Type.String({ description: "Directory to search in (default: current directory)" })),
	paths: Type.Optional(Type.Array(Type.String({ description: "Search roots. Mutually exclusive with path." }))),
	hidden: Type.Optional(Type.Boolean({ description: "Include hidden files and directories (default: true)" })),
	limit: Type.Optional(Type.Number({ description: "Maximum number of results (default: 1000)" })),
	timeoutMs: Type.Optional(Type.Number({ description: "Timeout in milliseconds (default: 5000)" })),
});

type FindInput = {
	pattern: string;
	path?: string;
	paths?: string[];
	hidden?: boolean;
	limit?: number;
	timeoutMs?: number;
};

const toPosix = (value: string): string => value.replace(/\\/g, "/");

const formatFindCall = (
	input: FindInput,
	theme: { fg: (token: string, text: string) => string; bold: (text: string) => string },
): string => {
	const pattern = typeof input.pattern === "string" ? input.pattern : "";
	const pathRoots = input.paths?.filter((entry) => typeof entry === "string" && entry.trim().length > 0) ?? [];
	const scope = pathRoots.length > 0 ? `paths:${summarizeList(pathRoots)}` : `path:${input.path ?? "."}`;
	const flags: string[] = [];
	if (input.hidden === false) flags.push("hidden:false");
	if (input.limit !== undefined) flags.push(`limit:${input.limit}`);
	if (input.timeoutMs !== undefined) flags.push(`timeoutMs:${input.timeoutMs}`);

	let line =
		theme.fg("toolTitle", theme.bold("find")) +
		" " +
		theme.fg("accent", pattern) +
		theme.fg("toolOutput", ` in ${scope}`);
	if (flags.length > 0) line += theme.fg("muted", ` [${flags.join(", ")}]`);
	return line;
};

const toolMissingMessage = (binary: string): string =>
	`'${binary}' is not available in PATH. Install ${binary} and ensure it is available in PATH.`;

type FindRenderDetails = {
	resultLimitReached?: number;
	truncation?: { truncated?: boolean };
};

const getCollapsedSummary = (
	rawText: string,
	details: FindRenderDetails,
	theme: { fg: (token: string, text: string) => string },
): string => {
	if (rawText === "No files found matching pattern") return rawText;
	const noticeIndex = rawText.indexOf("\n\n[");
	const filesBlock = noticeIndex >= 0 ? rawText.slice(0, noticeIndex) : rawText;
	const files = filesBlock
		.split("\n")
		.map((line) => line.trim())
		.filter(Boolean);
	if (files.length === 0) return rawText || "(no output)";

	const lines: string[] = [theme.fg("toolOutput", `${files.length} ${files.length === 1 ? "file" : "files"}`)];
	const notices: string[] = [];
	if (details.truncation?.truncated) notices.push(`${formatSize(DEFAULT_MAX_BYTES)} output limit`);
	if (notices.length > 0) lines.push(theme.fg("warning", notices.join(" · ")));
	lines.push(theme.fg("dim", `(${keyHint("app.tools.expand", "to expand")})`));
	return lines.join("\n");
};

const runFd = async (params: {
	pattern: string;
	rootAbsolute: string;
	includeHidden: boolean;
	limit: number;
	timeoutMs: number;
	signal?: AbortSignal;
}): Promise<string[]> => {
	const { pattern, rootAbsolute, includeHidden, limit, timeoutMs, signal } = params;
	const args = buildFdArgs(pattern, rootAbsolute, includeHidden, limit);

	return await runLineStreamingProcess<string>({
		command: "fd",
		args,
		maxResults: limit,
		timeoutMs,
		...(signal ? { signal } : {}),
		normalizeLine: (line) => line.replace(/\r$/, ""),
		skipEmptyLines: true,
		missingBinaryMessage: toolMissingMessage("fd"),
		runErrorLabel: "fd",
		exitErrorLabel: "fd",
		timeoutErrorMessage: (ms) => `find timed out after ${Math.max(1, Math.round(ms / 1000))}s`,
		parseLine: (line) => line,
	});
};

export default function findExtension(pi: ExtensionAPI) {
	const activate = () => ensureToolActive(pi, "find");
	pi.on("session_start", activate);
	pi.on("session_tree", activate);

	pi.registerTool({
		name: "find",
		label: "find",
		description:
			"Search files by glob pattern with optional multipath roots, hidden toggle, timeout, and deterministic dedupe. Output is truncated to 50KB.",
		promptSnippet: "Find files by glob pattern with optional hidden toggle and multipath",
		parameters: findSchema,
		renderCall(args, theme, context) {
			const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
			text.setText(formatFindCall(args as FindInput, theme));
			return text;
		},
		renderResult(result, options, theme, context) {
			const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
			const rawText = getFirstTextContent(result.content as Array<{ type: string; text?: string }>) || "(no output)";
			if (context.isError || options.expanded || options.isPartial) {
				text.setText(rawText);
				return text;
			}
			const summary = getCollapsedSummary(rawText, (result.details ?? {}) as FindRenderDetails, theme);
			text.setText(summary);
			return text;
		},
		async execute(_toolCallId, input: FindInput, signal, _onUpdate, ctx) {
			if (!input.pattern || input.pattern.trim().length === 0) {
				throw new Error("pattern must be a non-empty string");
			}

			const effectiveLimit = normalizeLimit(input.limit);
			const includeHidden = input.hidden ?? true;
			const timeoutMs = normalizeTimeout(input.timeoutMs);
			const roots = normalizeSearchRoots(input.path, input.paths);
			const deadline = Date.now() + timeoutMs;
			const cwd = ctx.cwd;
			const requestedCount = effectiveLimit + 1;
			const dedupe = new Set<string>();
			const collected: string[] = [];

			for (const root of roots) {
				if (collected.length >= requestedCount) break;
				const remainingTimeoutMs = deadline - Date.now();
				if (remainingTimeoutMs <= 0) {
					throw new Error(`find timed out after ${Math.max(1, Math.round(timeoutMs / 1000))}s`);
				}
				const absoluteRoot = path.resolve(cwd, root);
				let stat;
				try {
					stat = await fs.stat(absoluteRoot);
				} catch {
					throw new Error(`Path not found: ${root}`);
				}
				if (!stat.isDirectory()) {
					throw new Error(`Path is not a directory: ${root}`);
				}

				const remaining = requestedCount - collected.length;
				const matches = await runFd({
					pattern: input.pattern,
					rootAbsolute: absoluteRoot,
					includeHidden,
					limit: remaining,
					timeoutMs: remainingTimeoutMs,
					signal,
				});
				for (const matchPath of matches) {
					const resolved = path.isAbsolute(matchPath) ? matchPath : path.resolve(absoluteRoot, matchPath);
					const relativeToCwd = path.relative(cwd, resolved);
					const normalized = toPosix(relativeToCwd.length === 0 ? path.basename(resolved) : relativeToCwd);
					if (dedupe.has(normalized)) continue;
					dedupe.add(normalized);
					collected.push(normalized);
					if (collected.length >= requestedCount) break;
				}
			}

			collected.sort();
			const hasMore = collected.length > effectiveLimit;
			const selected = hasMore ? collected.slice(0, effectiveLimit) : collected;

			if (selected.length === 0) {
				return {
					content: [{ type: "text", text: "No files found matching pattern" }],
					details: undefined,
				};
			}

			const rawOutput = selected.join("\n");
			const truncation = truncateHead(rawOutput, {
				maxLines: Number.MAX_SAFE_INTEGER,
				maxBytes: DEFAULT_MAX_BYTES,
			});
			let output = truncation.content;
			const details: {
				resultLimitReached?: number;
				truncation?: ReturnType<typeof truncateHead>;
			} = {};
			const notices: string[] = [];
			if (hasMore) {
				notices.push(`${effectiveLimit} results limit reached`);
				details.resultLimitReached = effectiveLimit;
			}
			if (truncation.truncated) {
				notices.push(`${formatSize(DEFAULT_MAX_BYTES)} output limit reached`);
				details.truncation = truncation;
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
