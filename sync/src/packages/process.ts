import fs from "node:fs/promises";

import { Effect } from "effect";

import {
  commandExists,
  logCommandFailure,
  pickJsRunner,
  runCommand,
  runCommandOutcome,
  type CommandOutcome,
} from "@runtime/process.ts";
import { missingPackageRoots } from "./validate.ts";

export type { CommandOutcome } from "@runtime/process.ts";
export { runCommand } from "@runtime/process.ts";

export enum InferredInstallStep {
  Done = "Done",
  RetryWithNpm = "RetryWithNpm",
  ReportPrimaryFailure = "ReportPrimaryFailure",
}

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

    const tool = yield* pickJsRunner();
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
  timeoutMs: number,
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

    const tool = yield* pickJsRunner();
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
    const tool = yield* pickJsRunner();
    if (!tool) {
      console.error(`sync: no JS runtime available for build in ${dir}`);
      return false;
    }
    return yield* runCommand([tool, "run", "build"], dir, timeoutMs, "build");
  });

export const inferredInstallStep = (
  tool: string,
  npmAvailable: boolean,
  outcome: CommandOutcome,
): InferredInstallStep => {
  if (outcome._tag === "Success") {
    return InferredInstallStep.Done;
  }
  if (tool === "bun" && npmAvailable) {
    return InferredInstallStep.RetryWithNpm;
  }
  return InferredInstallStep.ReportPrimaryFailure;
};

export const inferredInstallCommand = (
  tool: string,
  missing: readonly string[],
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
