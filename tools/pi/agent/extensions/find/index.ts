import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { DEFAULT_MAX_BYTES, formatSize, truncateHead } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";
import { Type } from "@sinclair/typebox";
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

const ensureToolActive = (pi: ExtensionAPI, toolName: string): void => {
	const nextTools = new Set(pi.getActiveTools());
	if (nextTools.has(toolName)) return;
	nextTools.add(toolName);
	pi.setActiveTools(Array.from(nextTools));
};

const toPosix = (value: string): string => value.replace(/\\/g, "/");

const summarizeList = (items: string[], max = 2): string => {
	if (items.length <= max) return items.join(", ");
	return `${items.slice(0, max).join(", ")} +${items.length - max} more`;
};

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

	return await new Promise<string[]>((resolve, reject) => {
		const child = spawn("fd", args, { stdio: ["ignore", "pipe", "pipe"] });
		const lines = createInterface({ input: child.stdout });
		const matches: string[] = [];
		let stderr = "";
		let killedForLimit = false;
		let aborted = false;
		let timedOut = false;

		const timer = setTimeout(() => {
			timedOut = true;
			child.kill();
		}, timeoutMs);

		const stopChild = () => {
			if (!child.killed) {
				killedForLimit = true;
				child.kill();
			}
		};

		const cleanup = () => {
			clearTimeout(timer);
			lines.close();
			signal?.removeEventListener("abort", onAbort);
		};

		const onAbort = () => {
			aborted = true;
			child.kill();
		};
		signal?.addEventListener("abort", onAbort, { once: true });

		child.stderr.on("data", (chunk) => {
			stderr += chunk.toString();
		});

		lines.on("line", (line) => {
			const normalizedLine = line.replace(/\r$/, "");
			if (normalizedLine.length === 0) return;
			matches.push(normalizedLine);
			if (matches.length >= limit) {
				stopChild();
			}
		});

		child.on("error", (error) => {
			cleanup();
			if ((error as NodeJS.ErrnoException).code === "ENOENT") {
				reject(new Error(toolMissingMessage("fd")));
				return;
			}
			reject(new Error(`Failed to run fd: ${error.message}`));
		});

		child.on("close", (code) => {
			cleanup();
			if (aborted) {
				reject(new Error("Operation aborted"));
				return;
			}
			if (timedOut) {
				reject(new Error(`find timed out after ${Math.max(1, Math.round(timeoutMs / 1000))}s`));
				return;
			}
			if (!killedForLimit && code !== 0 && code !== 1) {
				const detail = stderr.trim() || `fd exited with code ${code}`;
				reject(new Error(detail));
				return;
			}
			resolve(matches);
		});
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
