import { spawn } from "node:child_process";
import { constants as fsConstants } from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";

import { Effect } from "effect";

export type CommandOutcome =
  | { readonly _tag: "Success" }
  | { readonly _tag: "MissingCommand" }
  | { readonly _tag: "Failure"; readonly detail: string }
  | { readonly _tag: "TimedOut" };

const detailFromOutput = (stdout: string, stderr: string): string => {
  if (stderr.trim()) {
    return stderr.trim();
  }
  if (stdout.trim()) {
    return stdout.trim();
  }
  return "unknown error";
};

export const commandExists = async (command: string): Promise<boolean> => {
  if (!command.includes(path.sep)) {
    return Boolean(Bun.which(command));
  }

  for (const candidate of [command]) {
    try {
      const metadata = await fs.stat(candidate);
      if (!metadata.isFile()) {
        continue;
      }
      await fs.access(candidate, fsConstants.X_OK);
      return true;
    } catch {
      continue;
    }
  }
  return false;
};

export const readPipe = async (stream: NodeJS.ReadableStream | null): Promise<Buffer> => {
  if (!stream) {
    return Buffer.alloc(0);
  }

  const chunks: Buffer[] = [];
  for await (const chunk of stream) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
};

export const runCommandOutcome = (
  command: readonly string[],
  cwd: string | undefined,
  timeoutMs: number,
): Effect.Effect<CommandOutcome> =>
  Effect.promise(async () => {
    try {
      const child = spawn(command[0]!, command.slice(1), {
        cwd: cwd ?? ".",
        stdio: ["ignore", "pipe", "pipe"],
      });

      const stdoutPromise = readPipe(child.stdout);
      const stderrPromise = readPipe(child.stderr);

      return await new Promise<CommandOutcome>((resolve, reject) => {
        let timedOut = false;
        const timer = setTimeout(() => {
          timedOut = true;
          child.kill("SIGKILL");
        }, timeoutMs);

        child.once("error", (error) => {
          clearTimeout(timer);
          const io = error as NodeJS.ErrnoException;
          if (io.code === "ENOENT") {
            resolve({ _tag: "MissingCommand" });
            return;
          }
          reject(error);
        });

        child.once("close", async (code) => {
          clearTimeout(timer);
          const stdout = (await stdoutPromise).toString("utf8");
          const stderr = (await stderrPromise).toString("utf8");

          if (timedOut) {
            resolve({ _tag: "TimedOut" });
            return;
          }
          if (code === 0) {
            resolve({ _tag: "Success" });
            return;
          }
          resolve({
            _tag: "Failure",
            detail: detailFromOutput(stdout, stderr),
          });
        });
      });
    } catch (error) {
      throw error as Error;
    }
  });

export const runCommand = (
  command: readonly string[],
  cwd: string | undefined,
  timeoutMs: number,
  action: string,
): Effect.Effect<boolean> =>
  Effect.gen(function* () {
    const outcome = yield* runCommandOutcome(command, cwd, timeoutMs);
    if (outcome._tag === "Success") {
      return true;
    }
    logCommandFailure(command, action, outcome);
    return false;
  });

export const logCommandFailure = (
  command: readonly string[],
  action: string,
  outcome: CommandOutcome,
): void => {
  switch (outcome._tag) {
    case "Success":
      return;
    case "MissingCommand":
      console.error(`sync: missing command for ${action}: ${command[0]}`);
      return;
    case "Failure":
      console.error(`sync: ${action} failed: ${command.join(" ")} (${outcome.detail})`);
      return;
    case "TimedOut":
      console.error(`sync: ${action} timed out: ${command.join(" ")}`);
  }
};

export const pickJsRunner = (): Effect.Effect<string | undefined> =>
  Effect.promise(async () => {
    if (await commandExists("bun")) {
      return "bun";
    }
    if (await commandExists("npm")) {
      return "npm";
    }
    return undefined;
  });
