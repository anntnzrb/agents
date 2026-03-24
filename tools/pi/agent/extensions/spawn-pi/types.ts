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
