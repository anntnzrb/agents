import type { TruncationResult } from "@mariozechner/pi-coding-agent";
import type { Message } from "@mariozechner/pi-ai";

export type SpawnMode = "single" | "parallel";
export type ChildRunStatus = "queued" | "running" | "completed" | "error";

export type TaskSpec = {
	index: number;
	task: string;
	cwd: string;
};

export type UsageStats = {
	input: number;
	output: number;
	cacheRead: number;
	cacheWrite: number;
	cost: number;
	contextTokens: number;
	turns: number;
};

export type ChildRunResult = {
	index: number;
	task: string;
	cwd: string;
	status: ChildRunStatus;
	exitCode: number;
	durationMs: number;
	messages: Message[];
	stderr: string;
	usage: UsageStats;
	toolCalls: number;
	model?: string;
	stopReason?: string;
	errorMessage?: string;
	currentTool?: string;
	latestText?: string;
};

export type SpawnPiDetails = {
	mode: SpawnMode;
	results: ChildRunResult[];
	truncation?: TruncationResult;
	fullOutputPath?: string;
};

export const emptyUsage = (): UsageStats => ({
	input: 0,
	output: 0,
	cacheRead: 0,
	cacheWrite: 0,
	cost: 0,
	contextTokens: 0,
	turns: 0,
});

export const createChildRunResult = (taskSpec: TaskSpec): ChildRunResult => ({
	index: taskSpec.index,
	task: taskSpec.task,
	cwd: taskSpec.cwd,
	status: "queued",
	exitCode: 0,
	durationMs: 0,
	messages: [],
	stderr: "",
	usage: emptyUsage(),
	toolCalls: 0,
});

export const cloneChildRunResult = (result: ChildRunResult): ChildRunResult => ({
	...result,
	messages: [...result.messages],
	usage: { ...result.usage },
});

export const didChildRunFail = (result: ChildRunResult): boolean =>
	result.exitCode !== 0 || result.status === "error";

export const getChildRunStatusLabel = (
	result: ChildRunResult,
): "completed" | "failed" => (didChildRunFail(result) ? "failed" : "completed");
