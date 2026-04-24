import { promises as fs } from "node:fs";
import path from "node:path";
import type { AgentToolResult, ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { createFindToolDefinition, DEFAULT_MAX_BYTES, formatSize, getAgentDir, truncateHead } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { runLineStreamingProcess } from "../_shared/line-process.js";
import { compactDisplayPath, toPosixPath } from "../_shared/path-utils.js";
import { getReusableText, joinRenderSegments, pluralize, type ColorTheme, type RenderTheme } from "../_shared/render-utils.js";
import { resolveSearchBinary } from "../_shared/search-binaries.js";
import { ensureToolActive, getFirstTextContent, summarizeList } from "../_shared/tool-utils.js";
import { buildFdArgs, DEFAULT_LIMIT, DEFAULT_TIMEOUT_MS, type FindKind, normalizeKind, normalizeLimit, normalizeSearchRoots, normalizeTimeout } from "./logic.js";

const OUTPUT_LIMIT_LABEL = formatSize(DEFAULT_MAX_BYTES);
const KIND_VALUES_LABEL = "file, directory, any";
const FIND_TOOL_DESCRIPTION = `Find files/directories by glob. Supports multipath roots, kind (${KIND_VALUES_LABEL}), hidden/gitignore controls, timeout, deterministic dedupe. Output truncated to ${OUTPUT_LIMIT_LABEL}.`;
const FIND_PROMPT_SNIPPET = "Find files/directories by glob: multipath, kind, hidden, ignore controls";

const PARAM_DESCRIPTIONS = {
	pattern: "Glob pattern, e.g. '*.ts', '**/*.json', 'src/**/*.spec.ts'",
	path: "Search directory (default: current directory)",
	paths: "Search roots; mutually exclusive with path",
	hidden: "Include hidden files/directories (default: true)",
	kind: `Result kind: ${KIND_VALUES_LABEL} (default: file)`,
	gitignore: "Respect .gitignore (default: true)",
	noIgnore: "Include ignored files; overrides gitignore",
	limit: `Max results (default: ${DEFAULT_LIMIT})`,
	timeoutMs: `Timeout ms (default: ${DEFAULT_TIMEOUT_MS})`,
} as const;

const findSchema = Type.Object({
	pattern: Type.String({ description: PARAM_DESCRIPTIONS.pattern }),
	path: Type.Optional(Type.String({ description: PARAM_DESCRIPTIONS.path })),
	paths: Type.Optional(Type.Array(Type.String({ description: PARAM_DESCRIPTIONS.paths }))),
	hidden: Type.Optional(Type.Boolean({ description: PARAM_DESCRIPTIONS.hidden })),
	kind: Type.Optional(Type.String({ description: PARAM_DESCRIPTIONS.kind })),
	gitignore: Type.Optional(Type.Boolean({ description: PARAM_DESCRIPTIONS.gitignore })),
	noIgnore: Type.Optional(Type.Boolean({ description: PARAM_DESCRIPTIONS.noIgnore })),
	limit: Type.Optional(Type.Number({ description: PARAM_DESCRIPTIONS.limit })),
	timeoutMs: Type.Optional(Type.Number({ description: PARAM_DESCRIPTIONS.timeoutMs })),
});

type FindInput = {
	pattern: string;
	path?: string;
	paths?: string[];
	hidden?: boolean;
	kind?: string;
	gitignore?: boolean;
	noIgnore?: boolean;
	limit?: number;
	timeoutMs?: number;
};

const RENDER_LABELS = {
	visible: "visible",
	gitignoreOff: "gitignore off",
	ignoredOn: "ignored on",
	limit: "limit",
} as const;

const formatFindCall = (input: FindInput, theme: RenderTheme): string => {
	const pattern = typeof input.pattern === "string" ? input.pattern : "";
	const pathRoots = input.paths?.filter((entry) => typeof entry === "string" && entry.trim().length > 0) ?? [];
	const scope = compactDisplayPath(pathRoots.length > 0 ? `paths:${summarizeList(pathRoots)}` : (input.path ?? "."));
	const flags: string[] = [theme.fg("accent", pattern)];
	if (input.kind && input.kind !== "file") flags.push(theme.fg("accent", input.kind));
	if (input.hidden === false) flags.push(theme.fg("muted", RENDER_LABELS.visible));
	if (input.gitignore === false) flags.push(theme.fg("warning", RENDER_LABELS.gitignoreOff));
	if (input.noIgnore === true) flags.push(theme.fg("warning", RENDER_LABELS.ignoredOn));
	if (input.limit !== undefined) flags.push(theme.fg("muted", `${RENDER_LABELS.limit}:${input.limit}`));
	if (input.timeoutMs !== undefined) flags.push(theme.fg("muted", `${input.timeoutMs}ms`));

	return joinRenderSegments([`${theme.fg("muted", "◇")} ${theme.fg("toolTitle", theme.bold("find"))} ${theme.fg("muted", scope)}`, ...flags], theme);
};

const toolMissingMessage = (binary: string): string =>
	`'${binary}' is not available in PATH. Install ${binary} and ensure it is available in PATH.`;

type FindRenderDetails = {
	resultLimitReached?: number;
	truncation?: { truncated?: boolean };
};

const getCollapsedSummary = (rawText: string, details: FindRenderDetails, theme: ColorTheme): string => {
	if (rawText === "No files found matching pattern") return `  ${rawText}`;
	const noticeIndex = rawText.indexOf("\n\n[");
	const filesBlock = noticeIndex >= 0 ? rawText.slice(0, noticeIndex) : rawText;
	const files = filesBlock
		.split("\n")
		.map((line) => line.trim())
		.filter(Boolean);
	if (files.length === 0) return rawText || "(no output)";

	const segments = [`↳ ${files.length} ${pluralize(files.length, "file")}`];
	if (details.truncation?.truncated) segments.push(theme.fg("warning", `${formatSize(DEFAULT_MAX_BYTES)} output limit`));
	return `  ${joinRenderSegments(segments, theme)}`;
};

const runFd = async (params: {
	command: string;
	pattern: string;
	rootAbsolute: string;
	includeHidden: boolean;
	kind: FindKind;
	useGitignore: boolean;
	limit: number;
	timeoutMs: number;
	signal?: AbortSignal;
}): Promise<string[]> => {
	const { command, pattern, rootAbsolute, includeHidden, kind, useGitignore, limit, timeoutMs, signal } = params;
	const args = buildFdArgs(pattern, rootAbsolute, includeHidden, limit, kind, useGitignore);

	return await runLineStreamingProcess<string>({
		command,
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

const ensureFdViaNativeFind = async (
	toolCallId: string,
	signal: AbortSignal,
	onUpdate: ((partial: AgentToolResult) => void) | undefined,
	cwd: string,
): Promise<void> => {
	const nativeFind = createFindToolDefinition(cwd);
	if (!nativeFind.execute) throw new Error("native find tool is unavailable");
	await nativeFind.execute(
		toolCallId,
		{
			pattern: "__pi_search_binary_bootstrap_never_match__",
			path: path.join(getAgentDir(), "bin"),
			limit: 1,
		},
		signal,
		onUpdate,
		{ cwd } as never,
	);
};

export const __test = {
	formatFindCall,
	getCollapsedSummary,
};

export default function findExtension(pi: ExtensionAPI) {
	const activate = () => ensureToolActive(pi, "find");
	pi.on("session_start", activate);
	pi.on("session_tree", activate);

	pi.registerTool({
		name: "find",
		label: "find",
		description: FIND_TOOL_DESCRIPTION,
		promptSnippet: FIND_PROMPT_SNIPPET,
		parameters: findSchema,
		renderShell: "self",
		renderCall(args, theme, context) {
			const text = getReusableText(context.lastComponent);
			text.setText(formatFindCall(args as FindInput, theme));
			return text;
		},
		renderResult(result, _options, theme, context) {
			const text = getReusableText(context.lastComponent);
			const rawText = getFirstTextContent(result.content as Array<{ type: string; text?: string }>) || "(no output)";
			if (context.isError) {
				text.setText(theme.fg("error", rawText));
				return text;
			}
			const summary = getCollapsedSummary(rawText, (result.details ?? {}) as FindRenderDetails, theme);
			text.setText(summary);
			return text;
		},
		async execute(toolCallId, input: FindInput, signal, onUpdate, ctx) {
			if (!input.pattern || input.pattern.trim().length === 0) {
				throw new Error("pattern must be a non-empty string");
			}

			const effectiveLimit = normalizeLimit(input.limit);
			const includeHidden = input.hidden ?? true;
			const kind = normalizeKind(input.kind);
			const useGitignore = input.noIgnore === true ? false : input.gitignore !== false;
			const timeoutMs = normalizeTimeout(input.timeoutMs);
			const roots = normalizeSearchRoots(input.path, input.paths);
			const deadline = Date.now() + timeoutMs;
			const cwd = ctx.cwd;
			const requestedCount = effectiveLimit + 1;
			let fdCommand = resolveSearchBinary("fd");
			if (!fdCommand) {
				await ensureFdViaNativeFind(toolCallId, signal, onUpdate, cwd);
				fdCommand = resolveSearchBinary("fd");
				if (!fdCommand) throw new Error("fd is unavailable after native Pi ensureTool fallback");
			}
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
					command: fdCommand,
					pattern: input.pattern,
					rootAbsolute: absoluteRoot,
					includeHidden,
					kind,
					useGitignore,
					limit: remaining,
					timeoutMs: remainingTimeoutMs,
					signal,
				});
				for (const matchPath of matches) {
					const resolved = path.isAbsolute(matchPath) ? matchPath : path.resolve(absoluteRoot, matchPath);
					const relativeToCwd = path.relative(cwd, resolved);
					const normalized = toPosixPath(relativeToCwd.length === 0 ? path.basename(resolved) : relativeToCwd);
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
