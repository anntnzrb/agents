import { constants as fsConstants } from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";

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

const hasPathSeparator = (command: string): boolean =>
  command.includes(path.sep) || command.includes("/") || command.includes("\\");

const resolveCommandPath = (command: string, cwd?: string): string =>
  hasPathSeparator(command) && cwd && !path.isAbsolute(command)
    ? path.resolve(cwd, command)
    : command;

const pathCommandCandidates = (command: string): string[] => {
  if (process.platform !== "win32" || path.extname(command)) {
    return [command];
  }
  const extensions = (process.env.PATHEXT ?? ".COM;.EXE;.BAT;.CMD")
    .split(";")
    .map((extension) => extension.trim())
    .filter((extension) => extension.length > 0);
  return [
    command,
    ...extensions.flatMap((extension) => [
      `${command}${extension.toLowerCase()}`,
      `${command}${extension.toUpperCase()}`,
    ]),
  ];
};

const executableForCommand = (command: string, cwd?: string): string => {
  const resolved = resolveCommandPath(command, cwd);
  return hasPathSeparator(resolved) ? resolved : (Bun.which(resolved) ?? resolved);
};

const existingPathCommand = async (command: string): Promise<string | undefined> => {
  for (const candidate of pathCommandCandidates(command)) {
    try {
      const metadata = await fs.stat(candidate);
      if (!metadata.isFile()) {
        continue;
      }
      await fs.access(candidate, fsConstants.X_OK);
      return candidate;
    } catch {
      continue;
    }
  }
  return undefined;
};

const resolveExecutable = async (command: string, cwd?: string): Promise<string | undefined> => {
  const executable = executableForCommand(command, cwd);
  if (!hasPathSeparator(executable)) {
    return Bun.which(executable) ?? undefined;
  }
  return await existingPathCommand(executable);
};

export const commandExists = async (command: string, cwd?: string): Promise<boolean> =>
  (await resolveExecutable(command, cwd)) !== undefined;

export const runCommandOutcome = async (
  command: readonly string[],
  cwd: string | undefined,
  timeoutMs: number,
): Promise<CommandOutcome> => {
  if (!command[0]) {
    return { _tag: "MissingCommand" };
  }

  const executable = await resolveExecutable(command[0], cwd);
  if (!executable) {
    return { _tag: "MissingCommand" };
  }

  const signal = AbortSignal.timeout(timeoutMs);
  const subprocess = Bun.spawn([executable, ...command.slice(1)], {
    cwd: cwd ?? ".",
    killSignal: "SIGKILL",
    signal,
    stdin: "ignore",
    stdout: "pipe",
    stderr: "pipe",
  });

  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(subprocess.stdout).text().catch(() => ""),
    new Response(subprocess.stderr).text().catch(() => ""),
    subprocess.exited,
  ]);

  if (signal.aborted) {
    return { _tag: "TimedOut" };
  }
  if (exitCode === 0) {
    return { _tag: "Success" };
  }
  return {
    _tag: "Failure",
    detail: detailFromOutput(stdout, stderr),
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
  }
};

export const pickBunRunner = async (): Promise<"bun" | undefined> =>
  (await commandExists("bun")) ? "bun" : undefined;
