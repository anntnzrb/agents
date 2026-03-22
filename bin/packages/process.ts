import fs from "node:fs/promises";
import { spawn } from "node:child_process";

import { Effect } from "effect";

import { commandExists, readPipe } from "../install.ts";
import { missingPackageRoots } from "./validate.ts";

export type CommandOutcome =
  | { readonly _tag: "Success" }
  | { readonly _tag: "MissingCommand" }
  | { readonly _tag: "Failure"; readonly detail: string }
  | { readonly _tag: "TimedOut" };

export enum InferredInstallStep {
  Done = "Done",
  RetryWithNpm = "RetryWithNpm",
  ReportPrimaryFailure = "ReportPrimaryFailure",
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

export const installPackageDeps = (dir: string, timeoutMs: number): Effect.Effect<boolean> =>
  Effect.gen(function* () {
    const hasPackageJson = yield* Effect.promise(() =>
      fs
        .stat(`${dir}/package.json`)
        .then((metadata) => metadata.isFile())
        .catch(() => false)
    );
    if (!hasPackageJson) {
      return true;
    }

    const tool = yield* jsRunner();
    if (!tool) {
      console.error(`sync: no JS package manager available for ${dir}`);
      return false;
    }

    const installCommand = [tool, "install"];
    if (!(yield* runCommand(installCommand, dir, timeoutMs, "install"))) {
      return false;
    }
    return yield* installInferredImportPackages(dir, timeoutMs);
  });

export const installInferredImportPackages = (
  dir: string,
  timeoutMs: number
): Effect.Effect<boolean> =>
  Effect.gen(function* () {
    let missing: string[];
    try {
      missing = missingPackageRoots(dir);
    } catch (error) {
      console.error(`sync: dependency scan failed in ${dir}: ${(error as Error).message}`);
      return false;
    }
    if (missing.length === 0) {
      return true;
    }
    if (!(yield* ensureInstallProject(dir))) {
      return false;
    }

    const tool = yield* jsRunner();
    if (!tool) {
      console.error(`sync: no JS package manager available for inferred imports in ${dir}`);
      return false;
    }

    const command = inferredInstallCommand(tool, missing);
    const outcome = yield* runCommandOutcome(command, dir, timeoutMs);
    switch (inferredInstallStep(tool, yield* Effect.promise(() => commandExists("npm")), outcome)) {
      case InferredInstallStep.Done:
        return true;
      case InferredInstallStep.RetryWithNpm: {
        console.error(
          `sync: retrying inferred package install with npm in ${dir} after bun resolution failed`
        );
        const fallback = inferredInstallCommand("npm", missing);
        const fallbackOutcome = yield* runCommandOutcome(fallback, dir, timeoutMs);
        if (fallbackOutcome._tag === "Success") {
          return true;
        }
        logCommandFailure(fallback, "install inferred packages via npm fallback", fallbackOutcome);
        return false;
      }
      case InferredInstallStep.ReportPrimaryFailure:
        logCommandFailure(command, "install inferred packages", outcome);
        return false;
    }
  });

export const runPackageBuild = (dir: string, timeoutMs: number): Effect.Effect<boolean> =>
  Effect.gen(function* () {
    const tool = yield* jsRunner();
    if (!tool) {
      console.error(`sync: no JS runtime available for build in ${dir}`);
      return false;
    }
    return yield* runCommand([tool, "run", "build"], dir, timeoutMs, "build");
  });

export const inferredInstallStep = (
  tool: string,
  npmAvailable: boolean,
  outcome: CommandOutcome
): InferredInstallStep => {
  if (outcome._tag === "Success") {
    return InferredInstallStep.Done;
  }
  if (tool === "bun" && npmAvailable) {
    return InferredInstallStep.RetryWithNpm;
  }
  return InferredInstallStep.ReportPrimaryFailure;
};

export const runCommand = (
  command: readonly string[],
  cwd: string | undefined,
  timeoutMs: number,
  action: string
): Effect.Effect<boolean> =>
  Effect.gen(function* () {
    const outcome = yield* runCommandOutcome(command, cwd, timeoutMs);
    if (outcome._tag === "Success") {
      return true;
    }
    logCommandFailure(command, action, outcome);
    return false;
  });

export const runCommandOutcome = (
  command: readonly string[],
  cwd: string | undefined,
  timeoutMs: number
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

export const logCommandFailure = (
  command: readonly string[],
  action: string,
  outcome: CommandOutcome
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

const jsRunner = (): Effect.Effect<string | undefined> =>
  Effect.promise(async () => {
    if (await commandExists("bun")) {
      return "bun";
    }
    if (await commandExists("npm")) {
      return "npm";
    }
    return undefined;
  });

export const inferredInstallCommand = (
  tool: string,
  missing: readonly string[]
): string[] =>
  tool === "bun"
    ? [tool, "add", "--no-save", ...missing]
    : [tool, "install", "--no-save", ...missing];

const ensureInstallProject = (dir: string): Effect.Effect<boolean> =>
  Effect.promise(async () => {
    try {
      await fs.stat(`${dir}/package.json`);
      return true;
    } catch {
      try {
        await fs.writeFile(
          `${dir}/package.json`,
          '{\n  "name": "pi-extension-deps",\n  "private": true\n}\n',
          "utf8"
        );
        return true;
      } catch (error) {
        const io = error as NodeJS.ErrnoException;
        console.error(`sync: write ${dir}/package.json (${io.message})`);
        return false;
      }
    }
  });
