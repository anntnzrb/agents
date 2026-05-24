import fs from "node:fs/promises";

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

export const InferredInstallStep = {
  Done: "Done",
  RetryWithNpm: "RetryWithNpm",
  ReportPrimaryFailure: "ReportPrimaryFailure",
} as const;

export type InferredInstallStep = (typeof InferredInstallStep)[keyof typeof InferredInstallStep];

export const installPackageDeps = async (dir: string, timeoutMs: number): Promise<boolean> => {
  const hasPackageJson = await fs
    .stat(`${dir}/package.json`)
    .then((metadata) => metadata.isFile())
    .catch(() => false);
  if (!hasPackageJson) {
    return true;
  }

  const tool = await pickJsRunner();
  if (!tool) {
    console.error(`sync: no JS package manager available for ${dir}`);
    return false;
  }

  const installCommand = [tool, "install"];
  if (!(await runCommand(installCommand, dir, timeoutMs, "install"))) {
    return false;
  }
  return await installInferredImportPackages(dir, timeoutMs);
};

export const installInferredImportPackages = async (
  dir: string,
  timeoutMs: number,
): Promise<boolean> => {
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
  if (!(await ensureInstallProject(dir))) {
    return false;
  }

  const tool = await pickJsRunner();
  if (!tool) {
    console.error(`sync: no JS package manager available for inferred imports in ${dir}`);
    return false;
  }

  const command = inferredInstallCommand(tool, missing);
  const outcome = await runCommandOutcome(command, dir, timeoutMs);
  switch (inferredInstallStep(tool, await commandExists("npm"), outcome)) {
    case InferredInstallStep.Done:
      return true;
    case InferredInstallStep.RetryWithNpm: {
      console.error(
        `sync: retrying inferred package install with npm in ${dir} after bun resolution failed`,
      );
      const fallback = inferredInstallCommand("npm", missing);
      const fallbackOutcome = await runCommandOutcome(fallback, dir, timeoutMs);
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
};

export const runPackageBuild = async (dir: string, timeoutMs: number): Promise<boolean> => {
  const tool = await pickJsRunner();
  if (!tool) {
    console.error(`sync: no JS runtime available for build in ${dir}`);
    return false;
  }
  return await runCommand([tool, "run", "build"], dir, timeoutMs, "build");
};

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

export const inferredInstallCommand = (tool: string, missing: readonly string[]): string[] =>
  tool === "bun"
    ? [tool, "add", "--no-save", ...missing]
    : [tool, "install", "--no-save", ...missing];

const ensureInstallProject = async (dir: string): Promise<boolean> => {
  try {
    await fs.stat(`${dir}/package.json`);
    return true;
  } catch {
    try {
      await fs.writeFile(
        `${dir}/package.json`,
        '{\n  "name": "pi-extension-deps",\n  "private": true\n}\n',
        "utf8",
      );
      return true;
    } catch (error) {
      const io = error as NodeJS.ErrnoException;
      console.error(`sync: write ${dir}/package.json (${io.message})`);
      return false;
    }
  }
};
