import { Effect, Schema } from "effect";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

type ExitCode = number | null;

export type RunLineStreamingProcessOptions<T> = {
  command: string;
  args: string[];
  maxResults: number;
  signal?: AbortSignal;
  timeoutMs?: number;
  normalizeLine?: (line: string) => string;
  skipEmptyLines?: boolean;
  parseLine: (line: string) => T | undefined;
  missingBinaryMessage: string;
  runErrorLabel?: string;
  exitErrorLabel?: string;
  allowedExitCodes?: readonly number[];
  abortErrorMessage?: string;
  timeoutErrorMessage?: (timeoutMs: number) => string;
};

export class SubprocessExecutionError extends Schema.TaggedError<SubprocessExecutionError>()(
  "SubprocessExecutionError",
  {
    command: Schema.String,
    message: Schema.String,
    cause: Schema.optional(Schema.Unknown),
  },
) {}

const processError = (
  command: string,
  message: string,
  cause?: unknown,
): SubprocessExecutionError =>
  new SubprocessExecutionError({ command, message, cause });

export const runLineStreamingProcessEffect = Effect.fn("runLineStreamingProcess")(<T>(
  options: RunLineStreamingProcessOptions<T>,
) => {
  const {
    command,
    args,
    maxResults,
    signal: explicitSignal,
    timeoutMs,
    normalizeLine,
    skipEmptyLines = false,
    parseLine,
    missingBinaryMessage,
    runErrorLabel = command,
    exitErrorLabel = command,
    allowedExitCodes = [0, 1],
    abortErrorMessage = "Operation aborted",
    timeoutErrorMessage = (ms) =>
      `${command} timed out after ${Math.max(1, Math.round(ms / 1000))}s`,
  } = options;

  const process = Effect.try({
    try: () => spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] }),
    catch: (cause) =>
      processError(command, `Failed to run ${runErrorLabel}: ${String(cause)}`, cause),
  }).pipe(
    Effect.flatMap((child) =>
      Effect.callback<T[], SubprocessExecutionError>((resume) => {
        const lines = createInterface({ input: child.stdout });
        const results: T[] = [];
        let stderr = "";
        let killedForLimit = false;
        let aborted = false;

        const stopChild = () => {
          if (!child.killed) {
            killedForLimit = true;
            child.kill();
          }
        };

        const cleanup = () => {
          lines.close();
          explicitSignal?.removeEventListener("abort", onAbort);
        };

        const onAbort = () => {
          aborted = true;
          child.kill();
        };

        explicitSignal?.addEventListener("abort", onAbort, { once: true });
        if (explicitSignal?.aborted) onAbort();

        child.stderr.on("data", (chunk: { toString: () => string }) => {
          stderr += chunk.toString();
        });

        lines.on("line", (rawLine) => {
          if (results.length >= maxResults) {
            stopChild();
            return;
          }

          try {
            const line = normalizeLine ? normalizeLine(rawLine) : rawLine;
            if (skipEmptyLines && line.length === 0) return;
            const parsed = parseLine(line);
            if (parsed === undefined) return;

            results.push(parsed);
            if (results.length >= maxResults) stopChild();
          } catch (cause) {
            cleanup();
            child.kill();
            resume(
              Effect.fail(
                processError(command, `Failed to parse ${runErrorLabel} output`, cause),
              ),
            );
          }
        });

        child.on("error", (cause: Error) => {
          cleanup();
          const message =
            (cause as NodeJS.ErrnoException).code === "ENOENT"
              ? missingBinaryMessage
              : `Failed to run ${runErrorLabel}: ${cause.message}`;
          resume(Effect.fail(processError(command, message, cause)));
        });

        child.on("close", (code: ExitCode) => {
          cleanup();
          if (aborted) {
            resume(Effect.fail(processError(command, abortErrorMessage)));
            return;
          }
          if (!killedForLimit && !allowedExitCodes.includes(code ?? -1)) {
            const detail = stderr.trim() || `${exitErrorLabel} exited with code ${code}`;
            resume(Effect.fail(processError(command, detail)));
            return;
          }
          resume(Effect.succeed(results));
        });

        return Effect.sync(() => {
          child.kill();
          cleanup();
        });
      }),
    ),
  );

  return timeoutMs === undefined
    ? process
    : process.pipe(
        Effect.timeoutOrElse({
          duration: timeoutMs,
          orElse: () =>
            Effect.fail(
              processError(command, timeoutErrorMessage(timeoutMs)),
            ),
        }),
      );
});

export function runLineStreamingProcess<T>(
  options: RunLineStreamingProcessOptions<T>,
): Promise<T[]> {
  return Effect.runPromise(runLineStreamingProcessEffect(options));
}
