import fs from "node:fs/promises";
import path from "node:path";

import { installInferredImportPackages } from "@packages/process.ts";
import { assertNever } from "@runtime/errors.ts";
import { type CommandOutcome, commandExists, runCommandOutcome } from "@runtime/process.ts";

export const iterExtensionPackages = async (root: string): Promise<string[]> => {
  const stat = await fs.stat(root).catch(() => undefined);
  if (!stat?.isDirectory()) {
    return [];
  }
  return walkExtensionPackages(root);
};

const walkExtensionPackages = async (root: string): Promise<string[]> => {
  const glob = new Bun.Glob("**/package.json");
  const packagesFound: string[] = [];
  try {
    for await (const match of glob.scan({ cwd: root, dot: false, followSymlinks: false })) {
      if (match.includes("node_modules/")) {
        continue;
      }
      packagesFound.push(path.dirname(path.join(root, match)));
    }
  } catch {
    return [];
  }
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

const chooseInstaller = async (): Promise<string[] | undefined> =>
  (await commandExists("bun")) ? ["bun", "install"] : undefined;

export const installExtensionDeps = async (
  root: string,
  sourceRoot: string,
  timeoutMs: number,
): Promise<boolean> => {
  const command = await chooseInstaller();
  if (!command) {
    console.error(`sync: bun is required for extension dependency install`);
    return false;
  }

  const results: boolean[] = [];
  for (const sourcePackageDir of await iterExtensionPackages(sourceRoot)) {
    const packageDir = path.join(root, path.relative(sourceRoot, sourcePackageDir));
    const hasPackageJson = await fs
      .stat(path.join(packageDir, "package.json"))
      .then((metadata) => metadata.isFile())
      .catch(() => false);
    if (!hasPackageJson) {
      results.push(true);
      continue;
    }

    results.push(await runInstall(command, packageDir, timeoutMs));
  }
  results.push(await installInferredImportPackages(root, timeoutMs, sourceRoot));
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
      return;
    default:
      assertNever(outcome);
  }
}
