import { spawn } from "node:child_process";
import { Effect, Schema } from "effect";
import type { Message } from "@earendil-works/pi-ai";
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
const WATCHDOG_PAYLOAD_ENV = "PI_SHARD_WATCHDOG_PAYLOAD";
const MAX_DEPTH = 1;
const FORCE_KILL_DELAY_MS = 5000;
const FINAL_DRAIN_DELAY_MS = 5000;
const POST_EXIT_STDIO_IDLE_MS = 2000;
const POST_EXIT_STDIO_HARD_MS = 8000;

class ShardTaskError extends Schema.TaggedError<ShardTaskError>()("ShardTaskError", {
  message: Schema.String,
  cause: Schema.Unknown,
}) {}

const WATCHDOG_SCRIPT = String.raw`
const { spawn, spawnSync } = require("node:child_process");
const FORCE_KILL_DELAY_MS = 5000;
const PARENT_CHECK_INTERVAL_MS = 1000;
const payloadRaw = process.env.PI_SHARD_WATCHDOG_PAYLOAD;
if (!payloadRaw) {
	console.error("PI_SHARD_WATCHDOG_PAYLOAD is required");
	process.exit(1);
}
let payload;
try {
	payload = JSON.parse(payloadRaw);
} catch (error) {
	console.error("invalid PI_SHARD_WATCHDOG_PAYLOAD: " + (error && error.message ? error.message : String(error)));
	process.exit(1);
}
const parentPid = Number(payload.parentPid);
const command = typeof payload.command === "string" ? payload.command : "";
const args = Array.isArray(payload.args) ? payload.args.filter((arg) => typeof arg === "string") : [];
const cwd = typeof payload.cwd === "string" ? payload.cwd : process.cwd();
const env = payload.env && typeof payload.env === "object" ? { ...process.env, ...payload.env } : process.env;
if (!Number.isSafeInteger(parentPid) || parentPid <= 0 || !command) {
	console.error("invalid watchdog payload");
	process.exit(1);
}
const detached = process.platform !== "win32";
const child = spawn(command, args, { cwd, detached, env, stdio: ["ignore", "pipe", "pipe"] });
let childExited = false;
let terminating = false;
let forceKillTimer;
const killChild = (signalName) => {
	if (childExited || !child.pid) return;
	if (process.platform === "win32") {
		spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
		return;
	}
	try {
		process.kill(-child.pid, signalName);
	} catch {
		try { child.kill(signalName); } catch {}
	}
};
const terminate = (signalName = "SIGTERM") => {
	if (terminating) return;
	terminating = true;
	killChild(signalName);
	forceKillTimer = setTimeout(() => killChild("SIGKILL"), FORCE_KILL_DELAY_MS);
};
const parentAlive = () => {
	try {
		process.kill(parentPid, 0);
		return true;
	} catch {
		return false;
	}
};
const parentCheckTimer = setInterval(() => {
	if (!parentAlive()) terminate("SIGTERM");
}, PARENT_CHECK_INTERVAL_MS);
child.stdout && child.stdout.pipe(process.stdout);
child.stderr && child.stderr.pipe(process.stderr);
child.on("error", (error) => {
	console.error(error.message);
	process.exitCode = 1;
	terminate("SIGTERM");
});
child.on("close", (code, signal) => {
	childExited = true;
	clearInterval(parentCheckTimer);
	if (forceKillTimer) clearTimeout(forceKillTimer);
	if (typeof code === "number") process.exit(code);
	if (signal) process.exit(1);
	process.exit(0);
});
process.on("SIGTERM", () => terminate("SIGTERM"));
process.on("SIGINT", () => terminate("SIGTERM"));
if (process.platform !== "win32") process.on("SIGHUP", () => terminate("SIGTERM"));
`;

type AbortLike = {
  aborted?: boolean;
  addEventListener: (
    type: "abort",
    listener: () => void,
    options?: { once?: boolean },
  ) => void;
  removeEventListener: (type: "abort", listener: () => void) => void;
};

type TerminationReason =
  | "aborted"
  | "timeout"
  | "maxTurns"
  | "maxToolCalls"
  | "finalDrain";

type SignalName = "SIGTERM" | "SIGKILL";

const activeChildPids = new Set<number>();

const killProcessGroupOrChild = (pid: number, signalName: SignalName): void => {
  if (process.platform === "win32") {
    const killer = spawn("taskkill", ["/PID", String(pid), "/T", "/F"], {
      stdio: "ignore",
      detached: true,
    });
    killer.unref();
    return;
  }
  try {
    process.kill(-pid, signalName);
    return;
  } catch {
    // Fall back to direct child kill below.
  }
  try {
    process.kill(pid, signalName);
  } catch {
    // Process already exited or cannot be signaled.
  }
};

export const killActiveChildProcesses = (
  signalName: SignalName = "SIGTERM",
): void => {
  for (const pid of activeChildPids) killProcessGroupOrChild(pid, signalName);
};

type ChildEvent =
  | { type: "agent_start" }
  | { type: "agent_end" }
  | {
      type: "tool_execution_start";
      toolName: string;
      args: Record<string, unknown>;
    }
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

const isAssistantMessage = (message: Message): boolean =>
  message.role === "assistant";

const messageHasToolCall = (message: Message): boolean =>
  Array.isArray(message.content) &&
  message.content.some((part) => isRecord(part) && part["type"] === "toolCall");

const isFinalAssistantStop = (message: Message): boolean =>
  isAssistantMessage(message) &&
  (message as { stopReason?: string }).stopReason === "stop" &&
  !messageHasToolCall(message);

const getNumber = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) ? value : 0;

const getCostTotal = (value: unknown): number => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (!isRecord(value)) return 0;
  return getNumber(value["total"]);
};

const clearCurrentTool = ({
  currentTool: _currentTool,
  ...result
}: ChildRunResult): ChildRunResult => result;

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
        (getNumber(message.usage.input) ||
          getNumber(message.usage.inputTokens)),
      output:
        nextResult.usage.output +
        (getNumber(message.usage.output) ||
          getNumber(message.usage.outputTokens)),
      cacheRead:
        nextResult.usage.cacheRead + getNumber(message.usage.cacheRead),
      cacheWrite:
        nextResult.usage.cacheWrite + getNumber(message.usage.cacheWrite),
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

  if (input.terminationReason === "finalDrain") {
    return {
      ...nextResult,
      status: "error",
      stopReason: "error",
      errorMessage: `child did not exit within ${FINAL_DRAIN_DELAY_MS}ms after final response`,
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

export const mapConcurrent = <TIn, TOut>(
  items: readonly TIn[],
  concurrency: number,
  fn: (item: TIn, index: number) => Promise<TOut>,
): Promise<TOut[]> => {
  if (items.length === 0) return Promise.resolve([]);
  const limit = Math.max(1, Math.min(concurrency, items.length));

  return Effect.runPromise(
    Effect.all(
      items.map((item, index) =>
        Effect.tryPromise({
          try: () => fn(item, index),
          catch: (cause) =>
            new ShardTaskError({
              message: cause instanceof Error ? cause.message : String(cause),
              cause,
            }),
        }),
      ),
      { concurrency: limit },
    ),
  );
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
    let finalDrainTimer: unknown;
    let postExitIdleTimer: unknown;
    let postExitHardTimer: unknown;
    let processExited = false;
    let stdoutEnded = false;
    let stderrEnded = false;

    const clearPostExitStdioTimers = () => {
      if (postExitIdleTimer) {
        clearTimeout(postExitIdleTimer);
        postExitIdleTimer = undefined;
      }
      if (postExitHardTimer) {
        clearTimeout(postExitHardTimer);
        postExitHardTimer = undefined;
      }
    };

    const finish = () => {
      if (settled) return;
      settled = true;
      if (timeoutTimer) clearTimeout(timeoutTimer);
      if (killTimer) clearTimeout(killTimer);
      if (finalDrainTimer) clearTimeout(finalDrainTimer);
      clearPostExitStdioTimers();
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

    const childEnv = {
      ...process.env,
      [DEPTH_ENV]: nextDepth,
    };
    const watchdogPayload = JSON.stringify({
      parentPid: process.pid,
      command: invocation.command,
      args: invocation.args,
      cwd: input.taskSpec.cwd,
      env: childEnv,
    });
    const detached = process.platform !== "win32";
    const proc = spawn(process.execPath, ["-e", WATCHDOG_SCRIPT], {
      cwd: input.taskSpec.cwd,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
      detached,
      env: {
        ...process.env,
        [WATCHDOG_PAYLOAD_ENV]: watchdogPayload,
      },
    });
    const childPid = typeof proc.pid === "number" ? proc.pid : undefined;
    if (childPid !== undefined) activeChildPids.add(childPid);

    const killChild = (signalName: SignalName) => {
      if (childPid !== undefined) {
        killProcessGroupOrChild(childPid, signalName);
        return;
      }
      proc.kill(signalName);
    };

    const terminateChild = (reason: TerminationReason) => {
      if (terminationReason) return;
      terminationReason = reason;
      if (finalDrainTimer) {
        clearTimeout(finalDrainTimer);
        finalDrainTimer = undefined;
      }
      killChild("SIGTERM");
      killTimer = setTimeout(() => {
        if (!settled) killChild("SIGKILL");
      }, FORCE_KILL_DELAY_MS);
    };

    const startFinalDrain = () => {
      if (settled || processExited || finalDrainTimer || terminationReason)
        return;
      finalDrainTimer = setTimeout(() => {
        if (!settled && !processExited) terminateChild("finalDrain");
      }, FINAL_DRAIN_DELAY_MS);
    };

    const destroyUnendedStdio = () => {
      if (!stdoutEnded) {
        try {
          proc.stdout?.destroy();
        } catch {
          // Ignore cleanup errors.
        }
      }
      if (!stderrEnded) {
        try {
          proc.stderr?.destroy();
        } catch {
          // Ignore cleanup errors.
        }
      }
    };

    const armPostExitStdioGuard = () => {
      if (!processExited || settled) return;
      if (postExitIdleTimer) clearTimeout(postExitIdleTimer);
      postExitIdleTimer = setTimeout(
        destroyUnendedStdio,
        POST_EXIT_STDIO_IDLE_MS,
      );
    };

    function abortChild() {
      terminateChild("aborted");
    }

    const enforceBudgets = () => {
      if (
        input.taskSpec.maxTurns !== undefined &&
        result.usage.turns > input.taskSpec.maxTurns
      ) {
        terminateChild("maxTurns");
        return;
      }
      if (
        input.taskSpec.maxToolCalls !== undefined &&
        result.toolCalls > input.taskSpec.maxToolCalls
      ) {
        terminateChild("maxToolCalls");
      }
    };

    const processLine = (line: string) => {
      if (!line.trim()) return;
      const event = parseChildEvent(line);
      if (!event) return;
      result = applyChildEvent(result, event);
      if (event.type === "message_end" && isFinalAssistantStop(event.message)) {
        startFinalDrain();
      }
      enforceBudgets();
      notify();
    };

    proc.stdout.on("data", (data: Uint8Array | string) => {
      armPostExitStdioGuard();
      stdoutBuffer += data.toString();
      const lines = stdoutBuffer.split("\n");
      stdoutBuffer = lines.pop() || "";
      for (const line of lines) processLine(line);
    });
    proc.stdout.on("end", () => {
      stdoutEnded = true;
      if (stdoutEnded && stderrEnded) clearPostExitStdioTimers();
    });

    proc.stderr.on("data", (data: Uint8Array | string) => {
      armPostExitStdioGuard();
      result = { ...result, stderr: `${result.stderr}${data.toString()}` };
      notify();
    });
    proc.stderr.on("end", () => {
      stderrEnded = true;
      if (stdoutEnded && stderrEnded) clearPostExitStdioTimers();
    });

    proc.on("exit", () => {
      processExited = true;
      if (finalDrainTimer) {
        clearTimeout(finalDrainTimer);
        finalDrainTimer = undefined;
      }
      armPostExitStdioGuard();
      postExitHardTimer = setTimeout(
        destroyUnendedStdio,
        POST_EXIT_STDIO_HARD_MS,
      );
    });

    proc.on("error", (error: Error) => {
      if (childPid !== undefined) activeChildPids.delete(childPid);
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
      if (childPid !== undefined) activeChildPids.delete(childPid);
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
