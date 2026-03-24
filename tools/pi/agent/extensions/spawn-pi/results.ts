import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import {
	DEFAULT_MAX_BYTES,
	DEFAULT_MAX_LINES,
	formatSize,
	getMarkdownTheme,
	truncateHead,
	withFileMutationQueue,
} from "@mariozechner/pi-coding-agent";
import type { Message } from "@mariozechner/pi-ai";
import { Container, Markdown, Spacer, Text } from "@mariozechner/pi-tui";
import type { ChildRunResult, SpawnPiDetails } from "./types.js";

const shorten = (text: string, max: number): string => (text.length > max ? `${text.slice(0, max)}...` : text);

export const formatTaskPreview = (task: string): string => shorten(task.replace(/\s+/g, " ").trim(), 70);

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
	const parts: string[] = [];
	const toolCalls = formatToolCalls(result.toolCalls);
	if (toolCalls) parts.push(toolCalls);
	if (result.usage.input > 0) parts.push(`↑${formatTokens(result.usage.input)}`);
	if (result.usage.output > 0) parts.push(`↓${formatTokens(result.usage.output)}`);
	return parts.join(" · ");
};

export const summarizeToolCall = (toolName: string, args: Record<string, unknown>): string => {
	switch (toolName) {
		case "bash":
			return shorten(String(args["command"] ?? "bash"), 60);
		case "read":
			return `read ${shorten(String(args["path"] ?? args["file_path"] ?? "?"), 48)}`;
		case "write":
			return `write ${shorten(String(args["path"] ?? args["file_path"] ?? "?"), 48)}`;
		case "edit":
			return `edit ${shorten(String(args["path"] ?? args["file_path"] ?? "?"), 48)}`;
		case "grep":
			return `grep ${shorten(String(args["pattern"] ?? "?"), 48)}`;
		case "find":
			return `find ${shorten(String(args["pattern"] ?? "*"), 48)}`;
		case "ls":
			return `ls ${shorten(String(args["path"] ?? "."), 48)}`;
		default:
			return toolName;
	}
};

const isAssistant = (message: Message): boolean => message.role === "assistant";

export const getAssistantText = (message: Message): string => {
	if (!isAssistant(message)) return "";
	return message.content
		.filter((part: { type: string }) => part.type === "text")
		.map((part: { text: string }) => part.text)
		.join("\n")
		.trim();
};

export const getFinalOutput = (messages: readonly Message[]): string => {
	for (let i = messages.length - 1; i >= 0; i--) {
		const message = messages[i];
		if (!message) continue;
		const text = getAssistantText(message);
		if (text) return text;
	}
	return "";
};

const buildHeader = (details: SpawnPiDetails): string => {
	if (details.results.length <= 1) return "spawn_pi";
	return `spawn_pi · ${details.results.length} tasks`;
};

const getActivityText = (result: ChildRunResult): string => {
	if (result.currentTool) return result.currentTool;
	if (result.status === "queued") return "waiting";
	const toolCalls = formatToolCalls(result.toolCalls);
	if (toolCalls) return toolCalls;
	return "working";
};

const buildProgressLines = (details: SpawnPiDetails): string[] =>
	details.results.map((result) => {
		const icon = result.status === "completed" ? "✓" : result.status === "error" ? "✗" : result.status === "running" ? "⏳" : "•";
		const activity = getActivityText(result);
		return `${icon} ${result.index + 1}. ${formatTaskPreview(result.task)} — ${shorten(activity.replace(/\s+/g, " ").trim(), 60)}`;
	});

export const buildToolContent = async (details: SpawnPiDetails): Promise<{ text: string; details: SpawnPiDetails }> => {
	const sections = details.results.map((result) => {
		const status = result.exitCode === 0 && result.status !== "error" ? "completed" : "failed";
		const output = getFinalOutput(result.messages) || result.stderr.trim() || result.errorMessage || "(no output)";
		return [
			`Task ${result.index + 1}: ${result.task}`,
			`Status: ${status}`,
			result.stopReason ? `Stop reason: ${result.stopReason}` : "",
			result.errorMessage ? `Error: ${result.errorMessage}` : "",
			result.stderr.trim() ? `Stderr:\n${result.stderr.trim()}` : "",
			`Output:\n${output}`,
		]
			.filter(Boolean)
			.join("\n\n");
	});

	const combined = sections.join("\n\n---\n\n");
	const truncation = truncateHead(combined, {
		maxLines: DEFAULT_MAX_LINES,
		maxBytes: DEFAULT_MAX_BYTES,
	});

	if (!truncation.truncated) return { text: truncation.content, details };

	const dir = await mkdtemp(path.join(tmpdir(), "pi-spawn-output-"));
	const filePath = path.join(dir, "output.txt");
	await withFileMutationQueue(filePath, async () => {
		await writeFile(filePath, combined, { encoding: "utf-8", mode: 0o600 });
	});

	const nextDetails: SpawnPiDetails = {
		...details,
		truncation,
		fullOutputPath: filePath,
	};

	const omittedLines = truncation.totalLines - truncation.outputLines;
	const omittedBytes = truncation.totalBytes - truncation.outputBytes;
	const notice = [
		"",
		`[Output truncated: showing ${truncation.outputLines} of ${truncation.totalLines} lines`,
		`(${formatSize(truncation.outputBytes)} of ${formatSize(truncation.totalBytes)}).`,
		`${omittedLines} lines (${formatSize(omittedBytes)}) omitted.`,
		`Full output saved to: ${filePath}]`,
	].join(" ");

	return {
		text: `${truncation.content}\n\n${notice.trim()}`,
		details: nextDetails,
	};
};

export const buildProgressText = (details: SpawnPiDetails): string => {
	const done = details.results.filter((result) => result.status === "completed" || result.status === "error").length;
	const total = details.results.length;
	return [`${buildHeader(details)} · ${done}/${total} done`, ...buildProgressLines(details)].join("\n");
};

export const renderCall = (args: { task?: string; tasks?: string[] }, theme: any) => {
	const taskCount = args.tasks && args.tasks.length > 0 ? args.tasks.length : args.task ? 1 : 0;
	let text = theme.fg("toolTitle", theme.bold("spawn_pi"));
	if (taskCount > 1) text += theme.fg("accent", ` · ${taskCount} tasks`);
	return new Text(text, 0, 0);
};

export const renderResult = (result: { content: Array<{ type: string; text?: string }>; details?: SpawnPiDetails }, options: { expanded: boolean; isPartial?: boolean }, theme: any) => {
	const details = result.details;
	if (!details || details.results.length === 0) {
		const text = result.content[0];
		return new Text(text?.type === "text" ? (text.text ?? "(no output)") : "(no output)", 0, 0);
	}

	if (options.isPartial) {
		return new Text(buildProgressLines(details).join("\n"), 0, 0);
	}

	if (!options.expanded) {
		const lines = details.results.map((task) => {
			const icon = task.exitCode === 0 && task.status !== "error" ? theme.fg("success", "✓") : theme.fg("error", "✗");
			const usage = formatUsage(task);
			const suffix = usage ? theme.fg("dim", ` · ${usage}`) : "";
			return `${icon} ${task.index + 1}. ${formatTaskPreview(task.task)}${suffix}`;
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
		const icon = task.exitCode === 0 && task.status !== "error" ? theme.fg("success", "✓") : theme.fg("error", "✗");
		container.addChild(new Text(`${icon} ${task.index + 1}. ${formatTaskPreview(task.task)}`, 0, 0));
		const usage = formatUsage(task);
		if (usage) container.addChild(new Text(theme.fg("dim", usage), 0, 0));
		if (task.stderr.trim()) container.addChild(new Text(theme.fg("error", task.stderr.trim()), 0, 0));
		const output = getFinalOutput(task.messages);
		if (output) {
			container.addChild(new Spacer(1));
			container.addChild(new Markdown(output.trim(), 0, 0, mdTheme));
		}
	}

	if (details.fullOutputPath) {
		container.addChild(new Spacer(1));
		container.addChild(new Text(theme.fg("dim", `Full output: ${details.fullOutputPath}`), 0, 0));
	}

	return container;
};
