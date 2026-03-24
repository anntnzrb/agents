import { spawn } from "node:child_process";
import type { Message } from "@mariozechner/pi-ai";
import { buildPiArgs, formatModelArg, getInheritedCliArgs, getPiInvocation } from "./cli.js";
import { getAssistantText, summarizeToolCall } from "./results.js";
import { type ChildRunResult, type TaskSpec, emptyUsage } from "./types.js";

const inheritedCliArgs = getInheritedCliArgs();
const DEPTH_ENV = "PI_SPAWN_DEPTH";
const MAX_DEPTH_ENV = "PI_SPAWN_MAX_DEPTH";
const DEFAULT_MAX_DEPTH = 1;

const parseDepth = (raw: string | undefined, fallback: number): number => {
	if (!raw || !/^\d+$/.test(raw)) return fallback;
	const parsed = Number(raw);
	return Number.isSafeInteger(parsed) ? parsed : fallback;
};

export const getDepthGuard = (): { currentDepth: number; maxDepth: number; canSpawn: boolean } => {
	const currentDepth = parseDepth(process.env[DEPTH_ENV], 0);
	const maxDepth = parseDepth(process.env[MAX_DEPTH_ENV], DEFAULT_MAX_DEPTH);
	return {
		currentDepth,
		maxDepth,
		canSpawn: currentDepth < maxDepth,
	};
};

const isAssistantMessage = (message: Message): boolean => message.role === "assistant";

const getCostTotal = (value: unknown): number => {
	if (typeof value === "number" && Number.isFinite(value)) return value;
	if (!value || typeof value !== "object") return 0;
	const total = (value as { total?: unknown }).total;
	return typeof total === "number" && Number.isFinite(total) ? total : 0;
};

const collectAssistantUsage = (result: ChildRunResult, message: Message): void => {
	if (!isAssistantMessage(message)) return;
	const usage = message.usage;
	if (!usage) return;
	result.usage.turns += 1;
	result.usage.input += usage.input || usage.inputTokens || 0;
	result.usage.output += usage.output || usage.outputTokens || 0;
	result.usage.cacheRead += usage.cacheRead || 0;
	result.usage.cacheWrite += usage.cacheWrite || 0;
	result.usage.cost += getCostTotal(usage.cost);
	result.usage.contextTokens = usage.totalTokens || result.usage.contextTokens;
	if (!result.model && message.model) result.model = message.model;
	if (message.stopReason) result.stopReason = message.stopReason;
	if (message.errorMessage) result.errorMessage = message.errorMessage;
	const latestText = getAssistantText(message);
	if (latestText) result.latestText = latestText;
};

export const mapConcurrent = async <TIn, TOut>(
	items: readonly TIn[],
	concurrency: number,
	fn: (item: TIn, index: number) => Promise<TOut>,
): Promise<TOut[]> => {
	if (items.length === 0) return [];
	const limit = Math.max(1, Math.min(concurrency, items.length));
	const results = new Array<TOut>(items.length);
	let nextIndex = 0;
	const workers = new Array(limit).fill(null).map(async () => {
		while (true) {
			const currentIndex = nextIndex++;
			if (currentIndex >= items.length) return;
			results[currentIndex] = await fn(items[currentIndex] as TIn, currentIndex);
		}
	});
	await Promise.all(workers);
	return results;
};

const clearCurrentTool = (result: ChildRunResult): void => {
	delete result.currentTool;
};

export const runChildTask = async (input: {
	taskSpec: TaskSpec;
	model?: { provider?: string; id?: string } | null;
	thinkingLevel?: string;
	signal?: AbortSignal;
	onChange?: (result: ChildRunResult) => void;
}): Promise<ChildRunResult> => {
	const result: ChildRunResult = {
		index: input.taskSpec.index,
		task: input.taskSpec.task,
		cwd: input.taskSpec.cwd,
		status: "queued",
		exitCode: 0,
		durationMs: 0,
		messages: [],
		stderr: "",
		usage: emptyUsage(),
	};

	const modelArg = formatModelArg(input.model);
	const args = buildPiArgs({
		task: input.taskSpec.task,
		modelArg,
		thinkingLevel: input.thinkingLevel,
		inheritedCliArgs,
	});
	const invocation = getPiInvocation(args);
	const startTime = Date.now();
	const nextDepth = String(parseDepth(process.env[DEPTH_ENV], 0) + 1);

	await new Promise<void>((resolve) => {
		let settled = false;
		const finish = () => {
			if (settled) return;
			settled = true;
			resolve();
		};

		const proc = spawn(invocation.command, invocation.args, {
			cwd: input.taskSpec.cwd,
			shell: false,
			stdio: ["ignore", "pipe", "pipe"],
			env: {
				...process.env,
				PI_OFFLINE: "1",
				[DEPTH_ENV]: nextDepth,
			},
		});

		let stdoutBuffer = "";
		let aborted = false;

		const notify = () => {
			result.durationMs = Date.now() - startTime;
			input.onChange?.({ ...result, messages: [...result.messages], usage: { ...result.usage } });
		};

		const killProc = () => {
			aborted = true;
			proc.kill("SIGTERM");
			setTimeout(() => {
				if (!proc.killed) proc.kill("SIGKILL");
			}, 5000);
		};

		const processLine = (line: string) => {
			if (!line.trim()) return;
			let event: any;
			try {
				event = JSON.parse(line);
			} catch {
				return;
			}

			switch (event.type) {
				case "agent_start":
					result.status = "running";
					clearCurrentTool(result);
					notify();
					return;
				case "tool_execution_start":
					result.status = "running";
					result.currentTool = summarizeToolCall(event.toolName, event.args ?? {});
					notify();
					return;
				case "tool_execution_end":
					clearCurrentTool(result);
					notify();
					return;
				case "message_end": {
					const message = event.message as Message | undefined;
					if (!message) return;
					result.messages.push(message);
					collectAssistantUsage(result, message);
					notify();
					return;
				}
				case "agent_end":
					clearCurrentTool(result);
					result.status = result.exitCode === 0 ? "completed" : result.status;
					notify();
					return;
				default:
					return;
			}
		};

		proc.stdout.on("data", (data: Buffer | string) => {
			stdoutBuffer += data.toString();
			const lines = stdoutBuffer.split("\n");
			stdoutBuffer = lines.pop() || "";
			for (const line of lines) processLine(line);
		});

		proc.stderr.on("data", (data: Buffer | string) => {
			result.stderr += data.toString();
			notify();
		});

		proc.on("error", (error: Error) => {
			result.status = "error";
			result.exitCode = 1;
			result.errorMessage = error.message;
			notify();
			finish();
		});

		proc.on("close", (code: number | null) => {
			if (stdoutBuffer.trim()) processLine(stdoutBuffer);
			result.exitCode = code ?? result.exitCode;
			result.durationMs = Date.now() - startTime;
			if (aborted) {
				result.status = "error";
				result.errorMessage = "spawn_pi aborted";
				notify();
				finish();
				return;
			}
			if (result.exitCode !== 0 || result.errorMessage || result.stopReason === "error" || result.stopReason === "aborted") {
				result.status = "error";
			} else {
				result.status = "completed";
			}
			notify();
			finish();
		});

		if (input.signal) {
			if (input.signal.aborted) {
				killProc();
			} else {
				input.signal.addEventListener("abort", killProc, { once: true });
			}
		}
	});

	return result;
};
