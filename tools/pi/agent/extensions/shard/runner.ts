import { spawn } from "node:child_process";
import type { Message } from "@mariozechner/pi-ai";
import type { InheritedCliArgs } from "./cli.js";
import { buildPiArgs, formatModelArg, getPiInvocation } from "./cli.js";
import { getAssistantText, summarizeToolCall } from "./results.js";
import {
	cloneChildRunResult,
	createChildRunResult,
	type ChildRunResult,
	type TaskSpec,
} from "./types.js";

const DEPTH_ENV = "PI_SHARD_DEPTH";
const MAX_DEPTH = 1;
const FORCE_KILL_DELAY_MS = 5000;

type AbortLike = {
	aborted?: boolean;
	addEventListener: (
		type: "abort",
		listener: () => void,
		options?: { once?: boolean },
	) => void;
	removeEventListener: (type: "abort", listener: () => void) => void;
};

type TerminationReason = "aborted" | "timeout" | "maxTurns" | "maxToolCalls";

type ChildEvent =
	| { type: "agent_start" }
	| { type: "agent_end" }
	| { type: "tool_execution_start"; toolName: string; args: Record<string, unknown> }
	| { type: "tool_execution_end" }
	| { type: "message_end"; message: Message };

const isRecord = (value: unknown): value is Record<string, unknown> =>
	typeof value === "object" && value !== null;

const parseDepth = (raw: string | undefined): number => {
	if (!raw || !/^\d+$/.test(raw)) return 0;
	const parsed = Number(raw);
	return Number.isSafeInteger(parsed) ? parsed : 0;
};

export const getDepthGuard = (): {
	currentDepth: number;
	maxDepth: number;
	canRun: boolean;
} => {
	const currentDepth = parseDepth(process.env[DEPTH_ENV]);
	return {
		currentDepth,
		maxDepth: MAX_DEPTH,
		canRun: currentDepth < MAX_DEPTH,
	};
};

const isAssistantMessage = (message: Message): boolean => message.role === "assistant";

const getNumber = (value: unknown): number =>
	typeof value === "number" && Number.isFinite(value) ? value : 0;

const getCostTotal = (value: unknown): number => {
	if (typeof value === "number" && Number.isFinite(value)) return value;
	if (!isRecord(value)) return 0;
	return getNumber(value["total"]);
};

const clearCurrentTool = ({ currentTool: _currentTool, ...result }: ChildRunResult): ChildRunResult =>
	result;

const appendMessage = (
	result: ChildRunResult,
	message: Message,
): ChildRunResult => {
	const nextResult: ChildRunResult = {
		...result,
		messages: [...result.messages, message],
	};

	if (!isAssistantMessage(message) || !message.usage) return nextResult;

	const latestText = getAssistantText(message);
	return {
		...nextResult,
		usage: {
			...nextResult.usage,
			turns: nextResult.usage.turns + 1,
			input:
				nextResult.usage.input +
				(getNumber(message.usage.input) || getNumber(message.usage.inputTokens)),
			output:
				nextResult.usage.output +
				(getNumber(message.usage.output) || getNumber(message.usage.outputTokens)),
			cacheRead: nextResult.usage.cacheRead + getNumber(message.usage.cacheRead),
			cacheWrite: nextResult.usage.cacheWrite + getNumber(message.usage.cacheWrite),
			cost: nextResult.usage.cost + getCostTotal(message.usage.cost),
			contextTokens:
				getNumber(message.usage.totalTokens) || nextResult.usage.contextTokens,
		},
		...(message.model ? { model: message.model } : {}),
		...(message.stopReason ? { stopReason: message.stopReason } : {}),
		...(message.errorMessage ? { errorMessage: message.errorMessage } : {}),
		...(latestText ? { latestText } : {}),
	};
};

const parseChildEvent = (line: string): ChildEvent | null => {
	let parsed: unknown;
	try {
		parsed = JSON.parse(line);
	} catch {
		return null;
	}

	if (!isRecord(parsed)) return null;
	const eventType = parsed["type"];
	if (typeof eventType !== "string") return null;

	switch (eventType) {
		case "agent_start":
			return { type: "agent_start" };
		case "agent_end":
			return { type: "agent_end" };
		case "tool_execution_start":
			return {
				type: "tool_execution_start",
				toolName:
					typeof parsed["toolName"] === "string" ? parsed["toolName"] : "tool",
				args: isRecord(parsed["args"])
					? (parsed["args"] as Record<string, unknown>)
					: {},
			};
		case "tool_execution_end":
			return { type: "tool_execution_end" };
		case "message_end":
			return isRecord(parsed["message"])
				? { type: "message_end", message: parsed["message"] as Message }
				: null;
		default:
			return null;
	}
};

const applyChildEvent = (
	result: ChildRunResult,
	event: ChildEvent,
): ChildRunResult => {
	switch (event.type) {
		case "agent_start":
			return clearCurrentTool({ ...result, status: "running" });
		case "tool_execution_start":
			return {
				...result,
				status: "running",
				toolCalls: result.toolCalls + 1,
				currentTool: summarizeToolCall(event.toolName, event.args),
			};
		case "tool_execution_end":
			return clearCurrentTool(result);
		case "message_end":
			return appendMessage(result, event.message);
		case "agent_end":
			return clearCurrentTool({ ...result, status: "completed" });
	}
};

export const finalizeChildRun = (
	result: ChildRunResult,
	input: {
		exitCode: number;
		durationMs: number;
		terminationReason?: TerminationReason;
		timeoutSec?: number;
		maxTurns?: number;
		maxToolCalls?: number;
	},
): ChildRunResult => {
	const nextResult = clearCurrentTool({
		...result,
		exitCode: input.exitCode,
		durationMs: input.durationMs,
	});

	if (input.terminationReason === "aborted") {
		return {
			...nextResult,
			status: "aborted",
			stopReason: "aborted",
			errorMessage: "aborted",
		};
	}

	if (input.terminationReason === "timeout") {
		return {
			...nextResult,
			status: "error",
			stopReason: "timeout",
			errorMessage: `timed out after ${input.timeoutSec ?? "?"}s`,
		};
	}

	if (input.terminationReason === "maxTurns") {
		return {
			...nextResult,
			status: "error",
			stopReason: "maxTurns",
			errorMessage: `exceeded maxTurns ${input.maxTurns ?? "?"}`,
		};
	}

	if (input.terminationReason === "maxToolCalls") {
		return {
			...nextResult,
			status: "error",
			stopReason: "maxToolCalls",
			errorMessage: `exceeded maxToolCalls ${input.maxToolCalls ?? "?"}`,
		};
	}

	const failed =
		nextResult.exitCode !== 0 ||
		Boolean(nextResult.errorMessage) ||
		nextResult.stopReason === "error" ||
		nextResult.stopReason === "aborted";

	return {
		...nextResult,
		status: failed ? "error" : "completed",
	};
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

	const workers = Array.from({ length: limit }, async () => {
		while (true) {
			const currentIndex = nextIndex;
			nextIndex += 1;
			if (currentIndex >= items.length) return;
			const item = items[currentIndex];
			if (item === undefined) return;
			results[currentIndex] = await fn(item, currentIndex);
		}
	});

	await Promise.all(workers);
	return results;
};

export const runChildTask = async (input: {
	taskSpec: TaskSpec;
	model?: { provider?: string; id?: string } | null;
	thinkingLevel?: string;
	inheritedCliArgs: InheritedCliArgs;
	runtimeTools?: readonly string[];
	signal?: AbortLike;
	onChange?: (result: ChildRunResult) => void;
}): Promise<ChildRunResult> => {
	let result = createChildRunResult(input.taskSpec);
	const modelArg = formatModelArg(input.model);
	const args = buildPiArgs({
		task: input.taskSpec.task,
		childMode: input.taskSpec.childMode,
		modelArg,
		thinkingLevel: input.thinkingLevel,
		inheritedCliArgs: input.inheritedCliArgs,
		...(input.runtimeTools ? { runtimeTools: input.runtimeTools } : {}),
	});
	const invocation = getPiInvocation(args);
	const startTime = Date.now();
	const nextDepth = String(getDepthGuard().currentDepth + 1);

	await new Promise<void>((resolve) => {
		let settled = false;
		let stdoutBuffer = "";
		let terminationReason: TerminationReason | undefined;
		let timeoutTimer: unknown;
		let killTimer: unknown;

		const finish = () => {
			if (settled) return;
			settled = true;
			if (timeoutTimer) clearTimeout(timeoutTimer);
			if (killTimer) clearTimeout(killTimer);
			if (input.signal) input.signal.removeEventListener("abort", abortChild);
			resolve();
		};

		const notify = () => {
			if (!input.onChange) return;
			input.onChange(
				cloneChildRunResult({
					...result,
					durationMs: Date.now() - startTime,
				}),
			);
		};

		const detached = process.platform !== "win32";
		const proc = spawn(invocation.command, invocation.args, {
			cwd: input.taskSpec.cwd,
			shell: false,
			stdio: ["ignore", "pipe", "pipe"],
			detached,
			env: {
				...process.env,
				[DEPTH_ENV]: nextDepth,
			},
		});

		const killChild = (signalName: "SIGTERM" | "SIGKILL") => {
			const pid = typeof proc.pid === "number" ? proc.pid : undefined;
			if (process.platform !== "win32" && pid) {
				try {
					process.kill(-pid, signalName);
					return;
				} catch {
					// Fall back to direct child kill below.
				}
			}
			proc.kill(signalName);
		};

		const terminateChild = (reason: TerminationReason) => {
			if (terminationReason) return;
			terminationReason = reason;
			killChild("SIGTERM");
			killTimer = setTimeout(() => {
				if (!settled) killChild("SIGKILL");
			}, FORCE_KILL_DELAY_MS);
		};

		function abortChild() {
			terminateChild("aborted");
		}

		const enforceBudgets = () => {
			if (input.taskSpec.maxTurns !== undefined && result.usage.turns > input.taskSpec.maxTurns) {
				terminateChild("maxTurns");
				return;
			}
			if (input.taskSpec.maxToolCalls !== undefined && result.toolCalls > input.taskSpec.maxToolCalls) {
				terminateChild("maxToolCalls");
			}
		};

		const processLine = (line: string) => {
			if (!line.trim()) return;
			const event = parseChildEvent(line);
			if (!event) return;
			result = applyChildEvent(result, event);
			enforceBudgets();
			notify();
		};

		proc.stdout.on("data", (data: Uint8Array | string) => {
			stdoutBuffer += data.toString();
			const lines = stdoutBuffer.split("\n");
			stdoutBuffer = lines.pop() || "";
			for (const line of lines) processLine(line);
		});

		proc.stderr.on("data", (data: Uint8Array | string) => {
			result = { ...result, stderr: `${result.stderr}${data.toString()}` };
			notify();
		});

		proc.on("error", (error: Error) => {
			if (settled) return;
			result = {
				...result,
				status: "error",
				exitCode: 1,
				errorMessage: error.message,
			};
			notify();
			finish();
		});

		proc.on("close", (code: number | null) => {
			if (settled) return;
			if (stdoutBuffer.trim()) processLine(stdoutBuffer);
			result = finalizeChildRun(result, {
				exitCode: code ?? result.exitCode,
				durationMs: Date.now() - startTime,
				...(terminationReason ? { terminationReason } : {}),
				...(input.taskSpec.timeoutSec !== undefined
					? { timeoutSec: input.taskSpec.timeoutSec }
					: {}),
				...(input.taskSpec.maxTurns !== undefined
					? { maxTurns: input.taskSpec.maxTurns }
					: {}),
				...(input.taskSpec.maxToolCalls !== undefined
					? { maxToolCalls: input.taskSpec.maxToolCalls }
					: {}),
			});
			notify();
			finish();
		});

		if (input.taskSpec.timeoutSec !== undefined) {
			timeoutTimer = setTimeout(() => {
				terminateChild("timeout");
			}, input.taskSpec.timeoutSec * 1000);
		}

		if (input.signal) {
			if (input.signal.aborted) {
				abortChild();
			} else {
				input.signal.addEventListener("abort", abortChild, { once: true });
			}
		}
	});

	return result;
};
