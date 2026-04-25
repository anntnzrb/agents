import { mkdtemp, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import {
	DEFAULT_MAX_BYTES,
	DEFAULT_MAX_LINES,
	formatSize,
	getMarkdownTheme,
	type Theme,
	truncateHead,
	type ToolRenderResultOptions,
	withFileMutationQueue,
	type AgentToolResult,
} from "@mariozechner/pi-coding-agent";
import type { Message } from "@mariozechner/pi-ai";
import { Container, Markdown, Spacer, Text } from "@mariozechner/pi-tui";
import { getChildRunStatusLabel, type ChildRunResult, type ToolDetails } from "./types.js";

const HOME_DIR = homedir();

const shorten = (text: string, max: number): string =>
	text.length > max ? `${text.slice(0, max)}...` : text;

const toSingleLine = (text: string): string => text.replace(/\s+/g, " ").trim();

const formatPreviewText = (text: string): string =>
	text
		.replace(/```([\w-]+)?\n?/g, "")
		.replace(/```/g, "")
		.replace(/`([^`]+)`/g, "$1")
		.replace(/\*\*([^*]+)\*\*/g, "$1")
		.replace(/__([^_]+)__/g, "$1")
		.replace(/^\s*[-*>#]+\s*/gm, "")
		.replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
		.replace(/\s+/g, " ")
		.trim();

const shortenPath = (value: string): string =>
	value.startsWith(HOME_DIR) ? `~${value.slice(HOME_DIR.length)}` : value;

const getPathArg = (args: Record<string, unknown>): string =>
	String(args["path"] ?? args["file_path"] ?? ".");

export const formatTaskPreview = (task: string): string =>
	shorten(toSingleLine(task), 70);

export const formatTokens = (count: number): string => {
	if (count < 1000) return count.toString();
	if (count < 10000) return `${(count / 1000).toFixed(1)}k`;
	if (count < 1000000) return `${Math.round(count / 1000)}k`;
	return `${(count / 1000000).toFixed(1)}M`;
};

const formatToolCalls = (count: number): string => {
	if (count <= 0) return "";
	return `${count} ${count === 1 ? "tool" : "tools"}`;
};

export const formatUsage = (result: ChildRunResult): string => {
	const parts = [
		formatToolCalls(result.toolCalls),
		result.usage.input > 0 ? `↑${formatTokens(result.usage.input)}` : "",
		result.usage.output > 0 ? `↓${formatTokens(result.usage.output)}` : "",
	].filter(Boolean);

	return parts.join(" · ");
};

export const summarizeToolCall = (
	toolName: string,
	args: Record<string, unknown>,
): string => {
	switch (toolName) {
		case "bash":
			return `$ ${shorten(toSingleLine(String(args["command"] ?? "bash")), 72)}`;
		case "pwsh":
			return `PS> ${shorten(toSingleLine(String(args["command"] ?? "pwsh")), 70)}`;
		case "read": {
			const path = shortenPath(getPathArg(args));
			const offset = Number(args["offset"] ?? 1);
			const limit = Number(args["limit"]);
			const hasOffset = Number.isFinite(offset);
			const hasLimit = Number.isFinite(limit);
			if (!hasOffset && !hasLimit) return `read ${shorten(path, 56)}`;
			const start = hasOffset ? Math.max(1, Math.trunc(offset)) : 1;
			const end = hasLimit ? start + Math.max(0, Math.trunc(limit)) - 1 : null;
			const lines = end ? `:${start}-${end}` : `:${start}`;
			return `read ${shorten(path, 52)}${lines}`;
		}
		case "write": {
			const path = shortenPath(getPathArg(args));
			const content = String(args["content"] ?? "");
			const lineCount = content ? content.split("\n").length : 0;
			const suffix = lineCount > 1 ? ` (${lineCount} lines)` : "";
			return `write ${shorten(path, 52)}${suffix}`;
		}
		case "edit":
			return `edit ${shorten(shortenPath(getPathArg(args)), 56)}`;
		case "grep":
			return `grep /${shorten(toSingleLine(String(args["pattern"] ?? "?")), 24)}/ in ${shorten(shortenPath(getPathArg(args)), 28)}`;
		case "find":
			return `find ${shorten(toSingleLine(String(args["pattern"] ?? "*")), 24)} in ${shorten(shortenPath(getPathArg(args)), 28)}`;
		case "ls":
			return `ls ${shorten(shortenPath(getPathArg(args)), 56)}`;
		default:
			return `${toolName} ${shorten(toSingleLine(JSON.stringify(args)), 48)}`;
	}
};

const isAssistant = (message: Message): boolean => message.role === "assistant";

export const getAssistantText = (message: Message): string => {
	if (!isAssistant(message)) return "";
	return message.content
		.filter((part) => part.type === "text")
		.map((part) => part.text ?? "")
		.join("\n")
		.trim();
};

export const getFinalOutput = (messages: readonly Message[]): string => {
	for (let index = messages.length - 1; index >= 0; index -= 1) {
		const message = messages[index];
		if (!message) continue;
		const text = getAssistantText(message);
		if (text) return text;
	}
	return "";
};

const buildHeader = (details: ToolDetails): string => {
	const segments = ["shard", details.childMode];
	if (details.results.length > 1) segments.push(`${details.results.length} tasks`);
	return segments.join(" · ");
};

const getResultStatusIcon = (result: ChildRunResult): string => {
	switch (result.status) {
		case "queued":
			return "◦";
		case "running":
			return "…";
		case "completed":
			return "✓";
		case "aborted":
			return "⊘";
		case "error":
			return "✗";
	}
};

const getResultStatusColor = (result: ChildRunResult): "dim" | "success" | "warning" | "error" => {
	switch (result.status) {
		case "queued":
			return "dim";
		case "running":
			return "warning";
		case "completed":
			return "success";
		case "aborted":
			return "warning";
		case "error":
			return "error";
	}
};

const getRawPreviewText = (result: ChildRunResult): string => {
	const errorPreview = toSingleLine(result.errorMessage || result.stderr);
	if (errorPreview) return errorPreview;
	return result.latestText || getFinalOutput(result.messages);
};

const getPreviewText = (result: ChildRunResult): string =>
	formatPreviewText(getRawPreviewText(result));

const getActivityText = (result: ChildRunResult): string => {
	if (result.status === "queued") return "queued";
	const latestPreview = getPreviewText(result);
	if (latestPreview && result.status === "running") return latestPreview;
	if (result.status === "running") return "thinking";
	if (result.status === "aborted" || result.stopReason === "aborted") return latestPreview || "aborted";
	if (result.status === "completed") return "done";
	if (result.status === "error") return latestPreview || "failed";
	return "working";
};

const buildProgressLines = (details: ToolDetails): string[] =>
	details.results.map((result) => {
		const activity = shorten(getActivityText(result), 72);
		const usage = formatUsage(result);
		const suffix = usage ? ` · ${usage}` : "";
		return `${getResultStatusIcon(result)} ${result.index + 1}. ${formatTaskPreview(result.task)} — ${activity}${suffix}`;
	});

const buildOutputSection = (result: ChildRunResult): string => {
	const output = getFinalOutput(result.messages);
	if (output) return `Output:\n${output}`;
	if (result.stderr.trim() || result.errorMessage) return "";
	return "Output:\n(no output)";
};

const buildResultSection = (result: ChildRunResult): string =>
	[
		`Task ${result.index + 1}: ${result.task}`,
		`Status: ${getChildRunStatusLabel(result)}`,
		result.stopReason ? `Stop reason: ${result.stopReason}` : "",
		result.errorMessage ? `Error: ${result.errorMessage}` : "",
		result.stderr.trim() ? `Stderr:\n${result.stderr.trim()}` : "",
		buildOutputSection(result),
	]
		.filter(Boolean)
		.join("\n\n");

const formatDuration = (durationMs: number): string => {
	if (durationMs < 1000) return `${durationMs}ms`;
	if (durationMs < 60000) return `${(durationMs / 1000).toFixed(1)}s`;
	return `${Math.round(durationMs / 60000)}m`;
};

const buildAggregateHeader = (details: ToolDetails): string => {
	const completed = details.results.filter((result) => getChildRunStatusLabel(result) === "completed").length;
	const aborted = details.results.filter((result) => getChildRunStatusLabel(result) === "aborted").length;
	const failed = details.results.filter((result) => getChildRunStatusLabel(result) === "failed").length;
	const durationMs = Math.max(0, ...details.results.map((result) => result.durationMs));
	const toolCalls = details.results.reduce((total, result) => total + result.toolCalls, 0);
	return [
		`shard: ${details.childMode}`,
		`${details.results.length} ${details.results.length === 1 ? "task" : "tasks"}`,
		`${completed} completed`,
		failed > 0 ? `${failed} failed` : "",
		aborted > 0 ? `${aborted} aborted` : "",
		durationMs > 0 ? formatDuration(durationMs) : "",
		toolCalls > 0 ? `${toolCalls} ${toolCalls === 1 ? "tool" : "tools"}` : "",
	]
		.filter(Boolean)
		.join(" · ");
};

const buildCombinedOutput = (details: ToolDetails): string =>
	[buildAggregateHeader(details), details.results.map(buildResultSection).join("\n\n---\n\n")].join("\n\n");

const persistFullOutput = async (content: string): Promise<string> => {
	const dir = await mkdtemp(join(tmpdir(), "pi-shard-output-"));
	const filePath = join(dir, "output.txt");
	await withFileMutationQueue(filePath, async () => {
		await writeFile(filePath, content, { encoding: "utf-8", mode: 0o600 });
	});
	return filePath;
};

const buildTruncationNotice = (
	filePath: string,
	truncation: ReturnType<typeof truncateHead>,
): string => {
	const outputLines = truncation.outputLines ?? 0;
	const outputBytes = truncation.outputBytes ?? 0;
	const omittedLines = truncation.totalLines - outputLines;
	const omittedBytes = truncation.totalBytes - outputBytes;
	return [
		"",
		`[Output truncated: showing ${outputLines} of ${truncation.totalLines} lines`,
		`(${formatSize(outputBytes)} of ${formatSize(truncation.totalBytes)}).`,
		`${omittedLines} lines (${formatSize(omittedBytes)}) omitted.`,
		`Full output saved to: ${filePath}]`,
	].join(" ");
};

export const buildToolContent = async (
	details: ToolDetails,
): Promise<{ text: string; details: ToolDetails }> => {
	const combined = buildCombinedOutput(details);
	const truncation = truncateHead(combined, {
		maxLines: DEFAULT_MAX_LINES,
		maxBytes: DEFAULT_MAX_BYTES,
	});

	if (!truncation.truncated) return { text: truncation.content, details };

	const fullOutputPath = await persistFullOutput(combined);
	const nextDetails: ToolDetails = {
		...details,
		truncation,
		fullOutputPath,
	};

	return {
		text: `${truncation.content}\n\n${buildTruncationNotice(fullOutputPath, truncation).trim()}`,
		details: nextDetails,
	};
};

export const buildProgressText = (details: ToolDetails): string =>
	buildProgressLines(details).join("\n");

type RenderCallArgs = Partial<{ tasks: string[]; mode: "worker" | "explorer" }>;

const deriveRenderMode = (args: RenderCallArgs, taskCount: number): "worker" | "explorer" | undefined =>
	args.mode ?? (taskCount === 1 ? "worker" : taskCount > 1 ? "explorer" : undefined);

const getResultIcon = (result: ChildRunResult, theme: Theme): string =>
	theme.fg(getResultStatusColor(result), getResultStatusIcon(result));

const getCompactStatusDetail = (result: ChildRunResult): string => {
	if (result.status === "completed") return "";
	return shorten(getActivityText(result), 72);
};

export const renderCall = (args: RenderCallArgs, theme: Theme) => {
	const taskCount = args.tasks?.length ?? 0;
	const childMode = deriveRenderMode(args, taskCount);
	let text = theme.fg("toolTitle", theme.bold("shard"));
	if (childMode) text += theme.fg("accent", ` · ${childMode}`);
	if (taskCount > 1) text += theme.fg("accent", ` · ${taskCount} tasks`);
	return new Text(text, 0, 0);
};

export const renderResult = (
	result: AgentToolResult<ToolDetails>,
	options: ToolRenderResultOptions,
	theme: Theme,
) => {
	const details = result.details;
	if (!details || details.results.length === 0) {
		const text = result.content[0];
		return new Text(
			text?.type === "text" ? (text.text ?? "(no output)") : "(no output)",
			0,
			0,
		);
	}

	if (options.isPartial) {
		return new Text(buildProgressText(details), 0, 0);
	}

	if (!options.expanded) {
		const lines = details.results.map((task) => {
			const usage = formatUsage(task);
			const statusDetail = getCompactStatusDetail(task);
			const detail = statusDetail ? theme.fg(getResultStatusColor(task), ` — ${statusDetail}`) : "";
			const suffix = usage ? theme.fg("dim", ` · ${usage}`) : "";
			return `${getResultIcon(task, theme)} ${task.index + 1}. ${formatTaskPreview(task.task)}${detail}${suffix}`;
		});
		return new Text(lines.join("\n"), 0, 0);
	}

	const container = new Container();
	const mdTheme = getMarkdownTheme();
	let header = theme.fg("toolTitle", theme.bold(buildHeader(details)));
	if (details.truncation?.truncated) header += theme.fg("warning", " (truncated)");
	container.addChild(new Text(header, 0, 0));

	for (const task of details.results) {
		container.addChild(new Spacer(1));
		container.addChild(
			new Text(
				`${getResultIcon(task, theme)} ${task.index + 1}. ${formatTaskPreview(task.task)}`,
				0,
				0,
			),
		);
		const usage = formatUsage(task);
		if (usage) container.addChild(new Text(theme.fg("dim", usage), 0, 0));
		if (task.errorMessage) {
			container.addChild(new Text(theme.fg("error", task.errorMessage), 0, 0));
		}
		if (task.stderr.trim()) {
			container.addChild(new Text(theme.fg("error", task.stderr.trim()), 0, 0));
		}
		const output = getFinalOutput(task.messages);
		if (output) {
			container.addChild(new Spacer(1));
			container.addChild(new Markdown(output.trim(), 0, 0, mdTheme));
		}
	}

	if (details.fullOutputPath) {
		container.addChild(new Spacer(1));
		container.addChild(
			new Text(theme.fg("dim", `Full output: ${details.fullOutputPath}`), 0, 0),
		);
	}

	return container;
};
