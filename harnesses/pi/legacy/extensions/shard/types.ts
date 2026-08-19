import type { TruncationResult } from "@earendil-works/pi-coding-agent";
import type { Message } from "@earendil-works/pi-ai";

export type RunMode = "single" | "parallel";
export type ChildMode = "worker" | "explorer";
export type ChildRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "aborted"
  | "error";

export type TaskSpec = {
  index: number;
  task: string;
  cwd: string;
  childMode: ChildMode;
  timeoutSec?: number;
  maxTurns?: number;
  maxToolCalls?: number;
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
  childMode: ChildMode;
  timeoutSec?: number;
  maxTurns?: number;
  maxToolCalls?: number;
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

export type ToolDetails = {
  mode: RunMode;
  childMode: ChildMode;
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
  childMode: taskSpec.childMode,
  ...(taskSpec.timeoutSec !== undefined
    ? { timeoutSec: taskSpec.timeoutSec }
    : {}),
  ...(taskSpec.maxTurns !== undefined ? { maxTurns: taskSpec.maxTurns } : {}),
  ...(taskSpec.maxToolCalls !== undefined
    ? { maxToolCalls: taskSpec.maxToolCalls }
    : {}),
  status: "queued",
  exitCode: 0,
  durationMs: 0,
  messages: [],
  stderr: "",
  usage: emptyUsage(),
  toolCalls: 0,
});

export const cloneChildRunResult = (
  result: ChildRunResult,
): ChildRunResult => ({
  ...result,
  messages: [...result.messages],
  usage: { ...result.usage },
});

export const didChildRunFail = (result: ChildRunResult): boolean =>
  result.exitCode !== 0 || result.status === "error";

export const getChildRunStatusLabel = (
  result: ChildRunResult,
): "completed" | "aborted" | "failed" =>
  result.status === "aborted" || result.stopReason === "aborted"
    ? "aborted"
    : didChildRunFail(result)
      ? "failed"
      : "completed";
