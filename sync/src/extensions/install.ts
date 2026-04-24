import fs from "node:fs/promises";
import path from "node:path";

import { installInferredImportPackages } from "@packages/process.ts";
import { commandExists, type CommandOutcome, runCommandOutcome } from "@runtime/process.ts";

export const iterExtensionPackages = async (root: string): Promise<string[]> => {
  const stat = await fs.stat(root).catch(() => undefined);
  if (!stat?.isDirectory()) {
    return [];
  }
  return walkExtensionPackages(root);
};

const walkExtensionPackages = async (root: string): Promise<string[]> => {
  const packagesFound: string[] = [];

  const visit = async (current: string): Promise<void> => {
    const entries = await fs.readdir(current, { withFileTypes: true });
    for (const entry of entries) {
      const entryPath = path.join(current, entry.name);
      if (entry.isSymbolicLink()) {
        continue;
      }
      if (entry.isDirectory()) {
        if (entry.name === "node_modules") {
          continue;
        }
        await visit(entryPath);
        continue;
      }
      if (entry.isFile() && entry.name === "package.json") {
        packagesFound.push(current);
      }
    }
  };

  await visit(root);
  return packagesFound;
};

export const runInstall = async (
  command: readonly string[],
  packageDir: string,
  timeoutMs: number,
): Promise<boolean> => {
  const outcome = await runCommandOutcome(command, packageDir, timeoutMs);
  if (outcome._tag === "Success") {
    return true;
  }
  logInstallFailure(command, packageDir, outcome);
  return false;
};

const needsNodeInstall = async (packageDir: string): Promise<boolean> => {
  const packageJson = await fs
    .stat(path.join(packageDir, "package.json"))
    .then((metadata) => metadata.isFile())
    .catch(() => false);
  const nodeModules = await fs.stat(path.join(packageDir, "node_modules")).catch(() => undefined);
  return packageJson && !nodeModules;
};

const chooseInstaller = async (packageDir: string): Promise<string[] | undefined> => {
  if (
    (await fs.stat(path.join(packageDir, "bun.lockb")).catch(() => undefined)) &&
    (await commandExists("bun"))
  ) {
    return ["bun", "install"];
  }
  if (await commandExists("npm")) {
    return ["npm", "install"];
  }
  if (await commandExists("bun")) {
    return ["bun", "install"];
  }
  return undefined;
};

export const installExtensionDeps = async (root: string, timeoutMs: number): Promise<boolean> => {
  const results: boolean[] = [];
  for (const packageDir of await iterExtensionPackages(root)) {
    if (!(await needsNodeInstall(packageDir))) {
      results.push(true);
      continue;
    }

    const command = await chooseInstaller(packageDir);
    if (!command) {
      console.error(`sync: no package manager available for ${packageDir}`);
      results.push(false);
      continue;
    }

    results.push(await runInstall(command, packageDir, timeoutMs));
  }
  results.push(await installInferredImportPackages(root, timeoutMs));
  return results.every(Boolean);
};

function logInstallFailure(
  command: readonly string[],
  packageDir: string,
  outcome: CommandOutcome,
): void {
  switch (outcome._tag) {
    case "Success":
      return;
    case "MissingCommand":
      console.error(`sync: missing installer: ${command[0]}`);
      return;
    case "Failure":
      console.error(
        `sync: deps install failed in ${packageDir}: ${command[0]} (${outcome.detail})`,
      );
      return;
    case "TimedOut":
      console.error(`sync: deps install timed out in ${packageDir}: ${command[0]}`);
  }
}
