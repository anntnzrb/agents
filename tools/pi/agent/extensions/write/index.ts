import { createHash, randomBytes } from "node:crypto";
import { existsSync } from "node:fs";
import { chmod, lstat, mkdir, open, readFile, readlink, realpath, rename, stat, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { createWriteToolDefinition, formatSize, type ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { getReusableText, joinRenderSegments, pluralize, type ColorTheme, type RenderTheme } from "../_shared/render-utils.js";
import { getUtf8ContentStats } from "../_shared/text-stats.js";
import { asString } from "../_shared/value-utils.js";

type WriteArgs = {
	path?: unknown;
	content?: unknown;
	expectedHash?: unknown;
};

type WriteRenderState = {
	marker?: "+" | "~" | "?";
};

const getWriteMarker = (rawPath: string, cwd: string): "+" | "~" | "?" => {
	if (rawPath.length === 0 || rawPath === "...") return "?";
	try {
		const absolutePath = path.isAbsolute(rawPath) ? rawPath : path.resolve(cwd, rawPath);
		return existsSync(absolutePath) ? "~" : "+";
	} catch {
		return "?";
	}
};

const formatWriteMarker = (marker: "+" | "~" | "?", theme: ColorTheme): string => {
	if (marker === "+") return theme.fg("toolDiffAdded", marker);
	if (marker === "~") return theme.fg("warning", marker);
	return theme.fg("muted", marker);
};

const writeSchema = {
	type: "object",
	properties: {
		path: { type: "string", description: "Path to the file to write (relative or absolute)" },
		content: { type: "string", description: "Content to write to the file" },
		expectedHash: {
			type: "string",
			description:
				"Optional SHA-256 hex hash of the current file contents. If provided, write fails when the existing file does not match.",
		},
	},
	required: ["path", "content"],
};

const sha256 = (content: Uint8Array): string => createHash("sha256").update(content).digest("hex");

type ExistingFileInfo = {
	mode: number;
	nlink: number;
};

const getExistingFileInfo = async (filePath: string): Promise<ExistingFileInfo | undefined> => {
	try {
		const info = await stat(filePath);
		return { mode: info.mode & 0o777, nlink: info.nlink };
	} catch {
		return undefined;
	}
};

const resolveWriteTarget = async (filePath: string): Promise<string> => {
	try {
		if (!(await lstat(filePath)).isSymbolicLink()) return filePath;
	} catch {
		return filePath;
	}
	try {
		return await realpath(filePath);
	} catch {
		const linkTarget = await readlink(filePath);
		return path.isAbsolute(linkTarget) ? linkTarget : path.resolve(path.dirname(filePath), linkTarget);
	}
};

const syncDirectory = async (dir: string): Promise<void> => {
	let handle: { sync: () => Promise<void>; close: () => Promise<void> } | undefined;
	try {
		handle = await open(dir, "r");
		await handle.sync();
	} catch {
		// Best effort: some platforms/filesystems do not allow directory fsync.
	} finally {
		await handle?.close().catch(() => undefined);
	}
};

const atomicWriteFile = async (filePath: string, content: string): Promise<void> => {
	const targetPath = await resolveWriteTarget(filePath);
	const dir = path.dirname(targetPath);
	const tmpPath = path.join(dir, `.pi-write-${Date.now()}-${randomBytes(6).toString("hex")}.tmp`);
	const existing = await getExistingFileInfo(targetPath);
	let handle: { writeFile: (value: string, encoding: string) => Promise<void>; sync: () => Promise<void>; close: () => Promise<void> } | undefined;

	if (existing && existing.nlink > 1) {
		await writeFile(targetPath, content, "utf8");
		return;
	}

	try {
		handle = await open(tmpPath, "w", existing?.mode);
		await handle.writeFile(content, "utf8");
		await handle.sync();
		await handle.close();
		handle = undefined;
		if (existing) await chmod(tmpPath, existing.mode).catch(() => undefined);
		await rename(tmpPath, targetPath);
		await syncDirectory(dir);
	} catch (error) {
		await handle?.close().catch(() => undefined);
		await unlink(tmpPath).catch(() => undefined);
		throw error;
	}
};

type HardenedWriteOperations = {
	mkdir: (dir: string) => Promise<void>;
	writeFile: (filePath: string, content: string) => Promise<void>;
};

type CreateWriteToolDefinition = (cwd: string, options?: { operations?: HardenedWriteOperations }) => ReturnType<typeof createWriteToolDefinition>;

const createNativeWriteToolDefinition = createWriteToolDefinition as CreateWriteToolDefinition;

const createHardenedWriteToolDefinition = (cwd: string, expectedHash?: string) =>
	createNativeWriteToolDefinition(cwd, {
		operations: {
			mkdir: (dir) => mkdir(dir, { recursive: true }).then(() => undefined),
			writeFile: async (filePath, content) => {
				if (expectedHash !== undefined) {
					let current: Uint8Array;
					try {
						current = (await readFile(filePath)) as Uint8Array;
					} catch {
						throw new Error(`Hash mismatch for ${filePath}: expected ${expectedHash}, got <missing file>`);
					}
					const actualHash = sha256(current);
					if (actualHash !== expectedHash) throw new Error(`Hash mismatch for ${filePath}: expected ${expectedHash}, got ${actualHash}`);
				}
				await atomicWriteFile(filePath, content);
			},
		},
	});

const executeWrite = (toolCallId: string, cwd: string, input: WriteArgs, signal: AbortSignal, onUpdate?: unknown, ctx?: unknown) => {
	const expectedHash = asString(input.expectedHash);
	const tool = createHardenedWriteToolDefinition(cwd, expectedHash);
	if (!tool.execute) throw new Error("native write tool is unavailable");
	return tool.execute(toolCallId, input, signal, onUpdate as never, ctx as never);
};

const buildCollapsedWriteCallText = (args: WriteArgs, marker: "+" | "~" | "?", theme: RenderTheme): string => {
	const rawPath = asString(args.path) ?? "...";
	const content = asString(args.content) ?? "";
	const stats = getUtf8ContentStats(content);
	const lines = `${stats.lines} ${pluralize(stats.lines, "line")}`;

	return joinRenderSegments(
		[
			`${theme.fg("muted", "▣")} ${theme.fg("toolTitle", theme.bold("write"))} ${formatWriteMarker(marker, theme)} ${theme.fg("muted", rawPath)}`,
			formatSize(stats.bytes),
			lines,
		],
		theme,
	);
};

export const __test = {
	atomicWriteFile,
	buildCollapsedWriteCallText,
	executeWrite: (cwd: string, input: WriteArgs) => executeWrite("test", cwd, input, undefined as never),
	formatWriteMarker,
	getContentStats: getUtf8ContentStats,
	sha256,
};

export default function writeExtension(pi: ExtensionAPI): void {
	const cwd = process.cwd();
	const baseWrite = createWriteToolDefinition(cwd);

	pi.registerTool({
		...baseWrite,
		parameters: writeSchema,
		renderShell: "self",
		async execute(toolCallId, input, signal, onUpdate, ctx) {
			return executeWrite(toolCallId, cwd, input as WriteArgs, signal, onUpdate, ctx);
		},
		renderCall(args, theme, context) {
			const state = context.state as WriteRenderState;
			const typedArgs = (args ?? {}) as WriteArgs;
			const rawPath = asString(typedArgs.path) ?? "...";
			if (!context.executionStarted) {
				state.marker = getWriteMarker(rawPath, context.cwd);
			} else if (state.marker === undefined) {
				state.marker = "?";
			}

			const text = getReusableText(context.lastComponent);
			text.setText(buildCollapsedWriteCallText(typedArgs, state.marker ?? "?", theme));
			return text;
		},
	});
}
