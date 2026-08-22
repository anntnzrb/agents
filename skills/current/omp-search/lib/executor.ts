import { Effect, FileSystem } from "effect";
import {
  OmpBinaryNotFoundError,
  type SearchFailurePayload,
  type SearchResult,
  type SearchSuccessPayload,
} from "./models.ts";
import { parseSearchOutput, redact, stripTerminalControls } from "./parser.ts";

export interface SingleSearchExecutionOptions {
  readonly queryWords: readonly string[];
  readonly provider?: string | undefined;
  readonly recency?: "day" | "week" | "month" | "year" | undefined;
  readonly limit?: number | undefined;
  readonly full?: boolean | undefined;
  readonly includeRaw?: boolean | undefined;
  readonly timeoutSeconds?: number | undefined;
  readonly ompBin?: string | undefined;
}

export const resolveOmp = (
  binary?: string | undefined
): Effect.Effect<string, OmpBinaryNotFoundError, FileSystem.FileSystem> =>
  Effect.gen(function* () {
    const candidate = binary || process.env["OMP_BIN"];
    if (candidate) {
      const fs = yield* FileSystem.FileSystem;
      const exists = yield* fs.exists(candidate).pipe(Effect.orElseSucceed(() => false));
      if (exists) {
        return candidate;
      }
    }

    const onPath = Bun.which("omp");
    if (onPath) {
      return onPath;
    }

    return yield* new OmpBinaryNotFoundError({
      message: "required executable 'omp' was not found on PATH or via OMP_BIN",
    });
  });

export function failureMessage(cleanedStdout: string, stderr: string, returnCode: number): string {
  for (const value of [stderr, cleanedStdout]) {
    const lines = value
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    const lastLine = lines[lines.length - 1];
    if (lastLine !== undefined) {
      return lastLine;
    }
  }
  return `omp search exited with code ${returnCode}`;
}

export const executeSingleSearch = (
  options: SingleSearchExecutionOptions,
  resolvedBinary: string
): Effect.Effect<SearchResult> =>
  Effect.gen(function* () {
    const fallbackQuery = options.queryWords.join(" ");
    const command: string[] = [resolvedBinary, "search"];

    if (options.provider) {
      command.push("--provider", options.provider);
    }
    if (options.recency) {
      command.push("--recency", options.recency);
    }
    if (options.limit !== undefined) {
      command.push("--limit", String(options.limit));
    }
    if (!options.full) {
      command.push("--compact");
    }
    command.push(...options.queryWords);
    const timeoutSeconds = options.timeoutSeconds ?? 300;
    const timeoutMs = timeoutSeconds * 1000;

    const env: Record<string, string> = {
      ...process.env,
      NO_COLOR: "1",
      FORCE_COLOR: "0",
    } as Record<string, string>;
    const result = yield* Effect.promise(async (signal: AbortSignal) => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        const proc = Bun.spawn(command, {
          env,
          stdin: "ignore",
          stdout: "pipe",
          stderr: "pipe",
          signal,
        });

        const timeoutPromise = new Promise<{ isTimeout: true }>((resolve) => {
          timer = setTimeout(() => resolve({ isTimeout: true }), timeoutMs);
          if (typeof timer === "object" && "unref" in timer && typeof timer.unref === "function") {
            timer.unref();
          }
          signal.addEventListener("abort", () => clearTimeout(timer), { once: true });
        });

        const completedPromise = (async () => {
          const [stdoutText, stderrText] = await Promise.all([
            new Response(proc.stdout).text(),
            new Response(proc.stderr).text(),
          ]);
          const exitCode = await proc.exited;
          return {
            isTimeout: false as const,
            stdout: stdoutText,
            stderr: stderrText,
            exitCode,
          };
        })();

        const outcome = await Promise.race([completedPromise, timeoutPromise]);
        clearTimeout(timer);

        if (outcome.isTimeout) {
          try {
            proc.kill();
          } catch {
            // proc may already be dead
          }
          const partialStdout = await new Response(proc.stdout).text().catch(() => "");
          const partialStderr = await new Response(proc.stderr).text().catch(() => "");
          return {
            isTimeout: true as const,
            stdout: partialStdout,
            stderr: partialStderr,
            exitCode: 124,
          };
        }

        return outcome;
      } catch (err: unknown) {
        clearTimeout(timer);
        return {
          isTimeout: false as const,
          stdout: "",
          stderr: err instanceof Error ? err.message : String(err),
          exitCode: 1,
        };
      }
    });

    if (result.isTimeout) {
      const partial = stripTerminalControls(result.stdout || result.stderr);
      const payload: SearchFailurePayload = {
        ok: false,
        query: fallbackQuery,
        provider: options.provider || "unknown",
        answer: "",
        sources: [],
        truncated: false,
        compact: !options.full,
        parsed: false,
        error: {
          code: "timeout",
          message: `omp search exceeded timeout (${timeoutSeconds}s)`,
        },
        exit_code: 124,
        ...(options.includeRaw ? { raw: partial } : {}),
      };
      return payload;
    }

    const parsed = parseSearchOutput(result.stdout, fallbackQuery);
    const cleanedStdout = parsed.cleanedRaw;

    if (result.exitCode === 0) {
      const provider = parsed.provider !== "unknown" ? parsed.provider : options.provider || "unknown";
      const payload: SearchSuccessPayload = {
        ok: true,
        query: parsed.query || fallbackQuery,
        provider,
        providers: [provider],
        providers_count: 1,
        answer: parsed.answer,
        sources: [...parsed.sources],
        sources_count: parsed.sources.length,
        truncated: parsed.truncated,
        compact: !options.full,
        parsed: parsed.parsed,
        exit_code: 0,
        ...(options.includeRaw ? { raw: cleanedStdout } : {}),
      };
      return payload;
    }

    const message = failureMessage(cleanedStdout, result.stderr, result.exitCode);
    const provider = parsed.provider !== "unknown" ? parsed.provider : options.provider || "unknown";
    const payload: SearchFailurePayload = {
      ok: false,
      query: parsed.query || fallbackQuery,
      provider,
      providers: [provider],
      providers_count: 1,
      answer: "",
      sources: [...parsed.sources],
      sources_count: parsed.sources.length,
      truncated: false,
      compact: !options.full,
      parsed: parsed.parsed,
      exit_code: result.exitCode,
      error: {
        code: "omp_search_failed",
        message,
      },
      ...(options.includeRaw ? { raw: parsed.cleanedRaw || undefined } : {}),
      ...(result.stderr.trim()
        ? { diagnostics: redact(stripTerminalControls(result.stderr)).slice(-2000) }
        : {}),
    };
    return payload;
  });
