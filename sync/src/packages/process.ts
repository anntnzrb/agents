import fs from "node:fs/promises";

import {
  logCommandFailure,
  pickBunRunner,
  runCommand,
  runCommandOutcome,
} from "@runtime/process.ts";
import { missingPackageRoots } from "./validate.ts";

export { runCommand } from "@runtime/process.ts";

export const installPackageDeps = async (
  dir: string,
  timeoutMs: number,
): Promise<boolean> => {
  const hasPackageJson = await fs
    .stat(`${dir}/package.json`)
    .then((metadata) => metadata.isFile())
    .catch(() => false);
  if (!hasPackageJson) {
    return true;
  }

  const tool = await pickBunRunner();
  if (!tool) {
    console.error(`sync: bun is required for dependency install in ${dir}`);
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
    console.error(
      `sync: dependency scan failed in ${dir}: ${(error as Error).message}`,
    );
    return false;
  }
  if (missing.length === 0) {
    return true;
  }
  if (!(await ensureInstallProject(dir))) {
    return false;
  }

  const tool = await pickBunRunner();
  if (!tool) {
    console.error(`sync: bun is required for inferred imports in ${dir}`);
    return false;
  }

  const command = [tool, "add", "--no-save", ...missing];
  const outcome = await runCommandOutcome(command, dir, timeoutMs);
  if (outcome._tag === "Success") {
    return true;
  }
  logCommandFailure(command, "install inferred packages", outcome);
  return false;
};

export const runPackageBuild = async (
  dir: string,
  timeoutMs: number,
): Promise<boolean> => {
  const tool = await pickBunRunner();
  if (!tool) {
    console.error(`sync: bun is required for build in ${dir}`);
    return false;
  }
  return await runCommand([tool, "run", "build"], dir, timeoutMs, "build");
};

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
