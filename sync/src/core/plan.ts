import fs from "node:fs";
import { join, posix } from "node:path";

import {
  harnessInstructionFileName,
  harnessInstructionTarget,
  harnessManagedStatePath,
  harnessRenameAsset,
  harnessRoot,
  harnessSourceRoot,
  SOURCE_AGENT_FILE,
  type Harness,
  type SyncEnv,
} from "./harness.ts";
import { panicMessage } from "../runtime/errors.ts";

export type JobKind = "File" | "Dir";

export interface Job {
  readonly src: string;
  readonly dst: string;
  readonly kind: JobKind;
  readonly scope?: "Tree" | "Children";
}

export interface HarnessPlan {
  readonly harness: Harness;
  readonly statePath: string;
  readonly root: string;
  readonly sourceRoot: string;
  readonly instructionTarget: string;
  readonly currentEntryNames: readonly string[];
  readonly cleanupEntryNames: readonly string[];
  readonly hooks: readonly SyncHookPlan[];
}

export interface SyncPlan {
  readonly harnesses: readonly HarnessPlan[];
  readonly jobs: readonly Job[];
  readonly hooks: readonly SyncHookPlan[];
}

export type SyncHookPlan = PackageBootstrapHookPlan | ExtensionDepsHookPlan;

export interface PackageBootstrapHookPlan {
  readonly kind: "PackageBootstrap";
  readonly harness: Harness;
  readonly manifestPath: string;
  readonly runtimeSettingsPath: string;
  readonly cacheRoot: string;
  readonly timeoutMs: number;
}

export interface ExtensionDepsHookPlan {
  readonly kind: "ExtensionDeps";
  readonly harness: Harness;
  readonly jobRoot: string;
  readonly root: string;
  readonly sourceRoot: string;
  readonly relativeRoot: string;
  readonly statePath: string;
  readonly timeoutMs: number;
}

export function buildSyncPlan(syncEnv: SyncEnv): SyncPlan {
  const assetNames = assetDirNames(syncEnv.assetsHome);
  const harnesses = syncEnv.harnesses.map((harness) => buildHarnessPlan(syncEnv, harness, assetNames));
  return {
    harnesses,
    jobs: [
      ...harnessDirJobs(harnesses),
      ...assetJobs(syncEnv, harnesses, assetNames),
      ...instructionJobs(syncEnv, harnesses),
      ...configJobs(syncEnv),
    ],
    hooks: harnesses.flatMap((plan) => plan.hooks),
  };
}

export function assetDirNames(root: string): string[] {
  return dirEntryNames(root, true);
}

export function topLevelEntryNames(root: string): string[] {
  return dirEntryNames(root, false);
}

function buildHarnessPlan(syncEnv: SyncEnv, harness: Harness, assetNames: readonly string[]): HarnessPlan {
  const root = harnessRoot(harness);
  const sourceRoot = harnessSourceRoot(harness, syncEnv.toolsHome);
  const instructionTarget = harnessInstructionTarget(harness);
  const currentEntryNames = currentManagedEntryNames(harness, sourceRoot, assetNames);
  const cleanupEntryNames = uniqueSorted([...currentEntryNames, ...harness.compatManagedEntries]);
  return {
    harness,
    statePath: harnessManagedStatePath(harness, syncEnv.managedStateHome),
    root,
    sourceRoot,
    instructionTarget,
    currentEntryNames,
    cleanupEntryNames,
    hooks: buildHookPlans(syncEnv, harness, root, sourceRoot),
  };
}

function currentManagedEntryNames(harness: Harness, sourceRoot: string, assetNames: readonly string[]): string[] {
  const names = new Set<string>();
  names.add(harnessInstructionFileName(harness));
  for (const entryName of topLevelEntryNames(sourceRoot)) {
    names.add(entryName);
  }
  for (const assetName of assetNames) {
    names.add(harnessRenameAsset(harness, assetName));
  }
  return uniqueSorted([...names]);
}

function harnessDirJobs(harnesses: readonly HarnessPlan[]): Job[] {
  return harnesses.map((plan) => ({
    src: plan.sourceRoot,
    dst: plan.root,
    kind: "Dir",
    scope: "Children",
  }));
}

function assetJobs(syncEnv: SyncEnv, harnesses: readonly HarnessPlan[], assetNames: readonly string[]): Job[] {
  const jobs: Job[] = [];
  for (const assetName of assetNames) {
    const assetPath = join(syncEnv.assetsHome, assetName);
    for (const plan of harnesses) {
      jobs.push({
        src: assetPath,
        dst: join(plan.root, harnessRenameAsset(plan.harness, assetName)),
        kind: "Dir",
        scope: "Tree",
      });
    }
  }
  return jobs;
}

function instructionJobs(syncEnv: SyncEnv, harnesses: readonly HarnessPlan[]): Job[] {
  return harnesses.map((plan) => ({
    src: join(syncEnv.assetsHome, SOURCE_AGENT_FILE),
    dst: plan.instructionTarget,
    kind: "File",
  }));
}

function configJobs(syncEnv: SyncEnv): Job[] {
  return [
    {
      src: join(syncEnv.assetsHome, "mcporter.jsonc"),
      dst: join(syncEnv.mcporterHome, "mcporter.json"),
      kind: "File",
    },
  ];
}

function buildHookPlans(
  syncEnv: SyncEnv,
  harness: Harness,
  root: string,
  sourceRoot: string,
): SyncHookPlan[] {
  return harness.hooks.map((hook) => {
    switch (hook.kind) {
      case "PackageBootstrap":
        return {
          kind: hook.kind,
          harness,
          manifestPath: join(sourceRoot, hook.manifestFile),
          runtimeSettingsPath: join(root, hook.settingsFile),
          cacheRoot: join(syncEnv.home, hook.cacheSubdir),
          timeoutMs: syncEnv.installTimeoutMs,
        };
      case "ExtensionDeps":
        return {
          kind: hook.kind,
          harness,
          jobRoot: root,
          root: join(root, hook.rootDir),
          sourceRoot: join(sourceRoot, hook.rootDir),
          relativeRoot: hook.rootDir,
          statePath: extensionHookStatePath(syncEnv.managedStateHome, harness),
          timeoutMs: syncEnv.installTimeoutMs,
        };
    }
  });
}

function extensionHookStatePath(managedStateHome: string, harness: Harness): string {
  return join(managedStateHome, `${harness.sourceName}.extension-deps.json`);
}

function dirEntryNames(root: string, dirsOnly: boolean): string[] {
  if (!isDirectory(root)) {
    return [];
  }

  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(root, { withFileTypes: true });
  } catch (error) {
    throw new Error(`read ${root} (${panicMessage(error)})`);
  }

  const names: string[] = [];
  for (const entry of entries) {
    if (dirsOnly && !entry.isDirectory()) {
      continue;
    }
    names.push(entry.name);
  }
  return uniqueSorted(names);
}

function uniqueSorted(names: readonly string[]): string[] {
  return [...new Set(names)].sort();
}

function isDirectory(root: string): boolean {
  try {
    return fs.statSync(root).isDirectory();
  } catch {
    return false;
  }
}

function isTopLevel(entryName: string): boolean {
  return entryName.length > 0 && !posix.isAbsolute(entryName) && !entryName.includes("/") && entryName !== "." && entryName !== "..";
}

export function isSafeManagedEntryName(entryName: string): boolean {
  return isTopLevel(entryName);
}
