import fs from "node:fs/promises";
import path from "node:path";

import { Effect } from "effect";

import { installInferredImportPackages } from "./packages/process.ts";
import {
  commandExists,
  type CommandOutcome,
  runCommandOutcome,
} from "./runtime/process.ts";

export { commandExists, readPipe } from "./runtime/process.ts";

export const iterExtensionPackages = (root: string): Effect.Effect<string[]> =>
  Effect.promise(async () => {
    const stat = await fs.stat(root).catch(() => undefined);
    if (!stat?.isDirectory()) {
      return [];
    }
    return walkExtensionPackages(root);
  });

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

export const runInstall = (
  command: readonly string[],
  packageDir: string,
  timeoutMs: number,
): Effect.Effect<boolean> =>
  Effect.gen(function* () {
    const outcome = yield* runCommandOutcome(command, packageDir, timeoutMs);
    if (outcome._tag === "Success") {
      return true;
    }
    logInstallFailure(command, packageDir, outcome);
    return false;
  });

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

export const installExtensionDeps = (root: string, timeoutMs: number) =>
  Effect.gen(function* () {
    const results: boolean[] = [];
    for (const packageDir of yield* iterExtensionPackages(root)) {
      if (!(yield* Effect.promise(() => needsNodeInstall(packageDir)))) {
        results.push(true);
        continue;
      }

      const command = yield* Effect.promise(() => chooseInstaller(packageDir));
      if (!command) {
        console.error(`sync: no package manager available for ${packageDir}`);
        results.push(false);
        continue;
      }

      results.push((yield* runInstall(command, packageDir, timeoutMs)) as boolean);
    }
    results.push(yield* installInferredImportPackages(root, timeoutMs));
    return results.every(Boolean);
  });

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
