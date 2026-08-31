import { constants as fsConstants } from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";
import { assertNever } from "./errors.ts";

export type CommandOutcome =
  | { readonly _tag: "Success" }
  | { readonly _tag: "MissingCommand" }
  | { readonly _tag: "Failure"; readonly detail: string }
  | { readonly _tag: "TimedOut" };

export interface ProcessResult {
  readonly exitCode: number;
  readonly stdout: string;
  readonly stderr: string;
  readonly timedOut: boolean;
}

export interface RunProcessOptions {
  readonly cwd?: string;
  readonly env?: Readonly<Record<string, string | undefined>>;
  readonly timeoutMs?: number;
  readonly stdio?: "pipe" | "inherit";
}

const detailFromOutput = (stdout: string, stderr: string): string => {
  if (stderr.trim()) {
    return stderr.trim();
  }
  if (stdout.trim()) {
    return stdout.trim();
  }
  return "unknown error";
};

const hasPathSeparator = (command: string): boolean =>
  command.includes(path.sep) || command.includes("/");

const resolveCommandPath = (command: string, cwd?: string): string =>
  hasPathSeparator(command) && cwd && !path.isAbsolute(command)
    ? path.resolve(cwd, command)
    : command;

const whichFromPath = async (
  command: string,
  env: NodeJS.ProcessEnv,
): Promise<string | undefined> => {
  const pathEnv = env["PATH"];
  if (!pathEnv) {
    return undefined;
  }
  for (const dir of pathEnv.split(path.delimiter)) {
    if (!dir) {
      continue;
    }
    const candidate = path.join(dir, command);
    try {
      const metadata = await fs.stat(candidate);
      if (!metadata.isFile()) {
        continue;
      }
      await fs.access(candidate, fsConstants.X_OK);
      return candidate;
    } catch {
      // try next directory
    }
  }
  return undefined;
};

const existingPathCommand = async (command: string): Promise<string | undefined> => {
  try {
    const metadata = await fs.stat(command);
    if (!metadata.isFile()) {
      return undefined;
    }
    await fs.access(command, fsConstants.X_OK);
    return command;
  } catch {
    return undefined;
  }
};

const resolveExecutable = async (
  command: string,
  cwd: string | undefined,
  env: NodeJS.ProcessEnv,
): Promise<string | undefined> => {
  const executable = resolveCommandPath(command, cwd);
  if (!hasPathSeparator(executable)) {
    return (await whichFromPath(executable, env)) ?? undefined;
  }
  return await existingPathCommand(executable);
};

export const commandExists = async (command: string, cwd?: string): Promise<boolean> =>
  (await resolveExecutable(command, cwd, process.env)) !== undefined;

export const runProcess = async (
  command: readonly string[],
  options: RunProcessOptions = {},
): Promise<ProcessResult> => {
  if (!command[0]) {
    return { exitCode: 127, stdout: "", stderr: "", timedOut: false };
  }

  const overrides =
    options.env === undefined
      ? undefined
      : Object.fromEntries(
          Object.entries(options.env).filter(
            (entry): entry is [string, string] => entry[1] !== undefined,
          ),
        );

  const childEnv = options.env === undefined ? process.env : { ...process.env, ...overrides };

  const executable = await resolveExecutable(command[0], options.cwd, childEnv);
  if (!executable) {
    return { exitCode: 127, stdout: "", stderr: "", timedOut: false };
  }

  const subprocess = Bun.spawn([executable, ...command.slice(1)], {
    ...(options.cwd ? { cwd: options.cwd } : {}),
    env: childEnv,
    detached: true,
    stdin: options.stdio === "inherit" ? "inherit" : "ignore",
    stdout: options.stdio ?? "pipe",
    stderr: options.stdio ?? "pipe",
  });

  let timedOut = false;
  let timer: Timer | undefined;
  let processExited = false;
  void subprocess.exited.then(() => {
    processExited = true;
  });

  if (options.timeoutMs !== undefined) {
    timer = setTimeout(() => {
      if (processExited || subprocess.exitCode !== null) {
        return;
      }
      timedOut = true;
      try {
        process.kill(-subprocess.pid, "SIGKILL");
      } catch {
        subprocess.kill("SIGKILL");
      }
    }, options.timeoutMs);
    timer.unref();
  }

  const stdio = options.stdio ?? "pipe";
  const stdoutHandle = subprocess.stdout;
  const stderrHandle = subprocess.stderr;

  try {
    const [stdout, stderr, exitCode] = await Promise.all([
      stdio === "pipe" && stdoutHandle !== undefined
        ? new Response(stdoutHandle).text().catch(() => "")
        : Promise.resolve(""),
      stdio === "pipe" && stderrHandle !== undefined
        ? new Response(stderrHandle).text().catch(() => "")
        : Promise.resolve(""),
      subprocess.exited,
    ]);
    return { exitCode, stdout, stderr, timedOut };
  } finally {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
  }
};

export const runCommandOutcome = async (
  command: readonly string[],
  cwd: string | undefined,
  timeoutMs: number,
): Promise<CommandOutcome> => {
  const options: RunProcessOptions = {
    timeoutMs,
    ...(cwd !== undefined ? { cwd } : {}),
  };
  const result = await runProcess(command, options);
  if (result.timedOut) {
    return { _tag: "TimedOut" };
  }
  if (result.exitCode === 127 && result.stdout === "" && result.stderr === "") {
    return { _tag: "MissingCommand" };
  }
  if (result.exitCode === 0) {
    return { _tag: "Success" };
  }
  return {
    _tag: "Failure",
    detail: detailFromOutput(result.stdout, result.stderr),
  };
};

export const runCommand = async (
  command: readonly string[],
  cwd: string | undefined,
  timeoutMs: number,
  action: string,
): Promise<boolean> => {
  const outcome = await runCommandOutcome(command, cwd, timeoutMs);
  if (outcome._tag === "Success") {
    return true;
  }
  logCommandFailure(command, action, outcome);
  return false;
};

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
      return;
    default:
      assertNever(outcome);
  }
};

export const pickBunRunner = async (): Promise<"bun" | undefined> =>
  Bun.which("bun") ? "bun" : undefined;
