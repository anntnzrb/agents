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

export const formatUsage = (result: ChildRunResult): string => {
	const parts: string[] = [];
	if (result.usage.turns > 0) parts.push(`${result.usage.turns}t`);
	if (result.usage.input > 0) parts.push(`↑${formatTokens(result.usage.input)}`);
	if (result.usage.output > 0) parts.push(`↓${formatTokens(result.usage.output)}`);
	if (result.usage.contextTokens > 0) parts.push(`ctx:${formatTokens(result.usage.contextTokens)}`);
	if (result.durationMs > 0) parts.push(`${(result.durationMs / 1000).toFixed(1)}s`);
	if (result.model) parts.push(result.model);
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
	const header = `${details.mode} · ${done}/${total} done`;
	const lines = details.results.map((result) => {
		const icon = result.status === "completed" ? "✓" : result.status === "error" ? "✗" : result.status === "running" ? "⏳" : "•";
		const activity = result.currentTool ?? result.latestText ?? "waiting";
		return `${icon} ${result.index + 1}. ${formatTaskPreview(result.task)} — ${shorten(activity.replace(/\s+/g, " ").trim(), 60)}`;
	});
	return [header, ...lines].join("\n");
};

export const renderCall = (args: { task?: string; tasks?: string[] }, theme: any) => {
	if (args.tasks && args.tasks.length > 0) {
		let text = theme.fg("toolTitle", theme.bold("spawn_pi ")) + theme.fg("accent", `parallel (${args.tasks.length})`);
		for (const task of args.tasks.slice(0, 3)) {
			text += `\n  ${theme.fg("dim", formatTaskPreview(task))}`;
		}
		if (args.tasks.length > 3) text += `\n  ${theme.fg("muted", `... +${args.tasks.length - 3} more`)}`;
		return new Text(text, 0, 0);
	}

	const preview = formatTaskPreview(args.task ?? "...");
	const text =
		theme.fg("toolTitle", theme.bold("spawn_pi ")) +
		theme.fg("accent", "single") +
		`\n  ${theme.fg("dim", preview)}`;
	return new Text(text, 0, 0);
};

export const renderResult = (result: { content: Array<{ type: string; text?: string }>; details?: SpawnPiDetails }, options: { expanded: boolean; isPartial?: boolean }, theme: any) => {
	const details = result.details;
	if (!details || details.results.length === 0) {
		const text = result.content[0];
		return new Text(text?.type === "text" ? (text.text ?? "(no output)") : "(no output)", 0, 0);
	}

	if (options.isPartial) {
		return new Text(buildProgressText(details), 0, 0);
	}

	if (!options.expanded) {
		const lines = details.results.map((task) => {
			const icon = task.exitCode === 0 && task.status !== "error" ? theme.fg("success", "✓") : theme.fg("error", "✗");
			const usage = formatUsage(task);
			const suffix = usage ? theme.fg("dim", ` ${usage}`) : "";
			return `${icon} ${formatTaskPreview(task.task)}${suffix}`;
		});
		let header = theme.fg("toolTitle", theme.bold("spawn_pi ")) + theme.fg("accent", `${details.mode}`);
		if (details.truncation?.truncated) header += theme.fg("warning", " (truncated)");
		return new Text([header, ...lines].join("\n"), 0, 0);
	}

	const container = new Container();
	const mdTheme = getMarkdownTheme();
	let header = theme.fg("toolTitle", theme.bold("spawn_pi ")) + theme.fg("accent", `${details.mode}`);
	if (details.truncation?.truncated) header += theme.fg("warning", " (truncated)");
	container.addChild(new Text(header, 0, 0));

	for (const task of details.results) {
		container.addChild(new Spacer(1));
		const icon = task.exitCode === 0 && task.status !== "error" ? theme.fg("success", "✓") : theme.fg("error", "✗");
		container.addChild(new Text(`${icon} ${formatTaskPreview(task.task)}`, 0, 0));
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
