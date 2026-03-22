import fs from "node:fs";
import { dirname, join, posix } from "node:path";

import { Harness, SyncEnv } from "./harness.ts";
import { err, panicMessage, rmEntry, warn } from "./lib.ts";

export interface ManagedSyncPlan {
  harnesses: ManagedHarnessPlan[];
}

export interface ManagedHarnessPlan {
  statePath: string;
  cleanupPaths: string[];
  currentEntryNames: string[];
}

export function planManagedEntries(syncEnv: SyncEnv): ManagedSyncPlan {
  return {
    harnesses: syncEnv.harnesses.map((harness) => planHarness(syncEnv, harness)),
  };
}

export function cleanManagedEntries(plan: ManagedSyncPlan): boolean {
  let success = true;
  for (const harness of plan.harnesses) {
    for (const path of harness.cleanupPaths) {
      try {
        rmEntry(path);
      } catch (error) {
        err(`cleanup failed: ${path} (${panicMessage(error)})`);
        success = false;
      }
    }
  }
  return success;
}

export function recordManagedEntries(plan: ManagedSyncPlan): boolean {
  let success = true;
  for (const harness of plan.harnesses) {
    try {
      writeRecordedEntryNames(harness.statePath, harness.currentEntryNames);
    } catch (error) {
      err(`managed state write failed: ${panicMessage(error)}`);
      success = false;
    }
  }
  return success;
}

export function assetDirNames(path: string): string[] {
  return dirEntryNames(path, true);
}

export function topLevelEntryNames(path: string): string[] {
  return dirEntryNames(path, false);
}

export function loadRecordedEntryNames(path: string): string[] {
  let content: string;
  try {
    content = fs.readFileSync(path, "utf8");
  } catch (error) {
    if (isNotFound(error)) {
      return [];
    }
    throw new Error(`read ${path} (${panicMessage(error)})`);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch (error) {
    warn(`managed state parse failed, ignoring ${path} (${panicMessage(error)})`);
    return [];
  }

  if (!Array.isArray(parsed)) {
    warn(`managed state parse failed, ignoring ${path} (not an array)`);
    return [];
  }
  if (!parsed.every((entryName) => typeof entryName === "string")) {
    warn(`managed state parse failed, ignoring ${path} (entries must be strings)`);
    return [];
  }

  const safeNames = new Set<string>();
  for (const entryName of parsed) {
    const safeName = safeTopLevelEntryName(entryName);
    if (safeName) {
      safeNames.add(safeName);
    } else {
      warn(`ignoring unsafe managed entry ${JSON.stringify(entryName)} in ${path}`);
    }
  }
  return [...safeNames].sort();
}

export function writeRecordedEntryNames(path: string, entryNames: string[]): void {
  const parent = dirname(path);
  try {
    fs.mkdirSync(parent, { recursive: true });
  } catch (error) {
    throw new Error(`create ${parent} (${panicMessage(error)})`);
  }

  let content: string;
  try {
    content = `${JSON.stringify(entryNames, null, 2)}\n`;
  } catch (error) {
    throw new Error(`serialize ${path} (${panicMessage(error)})`);
  }
  const { tempPath, fd } = createTempStateFile(path);
  try {
    try {
      fs.writeFileSync(fd, content, "utf8");
    } catch (error) {
      throw new Error(`write ${tempPath} (${panicMessage(error)})`);
    }
    try {
      fs.fsyncSync(fd);
    } catch (error) {
      throw new Error(`sync ${tempPath} (${panicMessage(error)})`);
    }
    try {
      fs.closeSync(fd);
    } catch {
      // ignore
    }
    try {
      fs.renameSync(tempPath, path);
    } catch (error) {
      throw new Error(`replace ${path} (${panicMessage(error)})`);
    }
  } catch (error) {
    try {
      fs.closeSync(fd);
    } catch {
      // ignore
    }
    try {
      fs.rmSync(tempPath, { force: true });
    } catch {
      // ignore
    }
    throw error;
  }
}

function dirEntryNames(path: string, dirsOnly: boolean): string[] {
  if (!isDirectory(path)) {
    return [];
  }

  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(path, { withFileTypes: true });
  } catch (error) {
    throw new Error(`read ${path} (${panicMessage(error)})`);
  }
  const names: string[] = [];
  for (const entry of entries) {
    if (dirsOnly && !entry.isDirectory()) {
      continue;
    }
    names.push(entry.name);
  }
  names.sort();
  return names;
}

function planHarness(syncEnv: SyncEnv, harness: Harness): ManagedHarnessPlan {
  const currentEntryNames = currentManagedEntryNames(syncEnv, harness);
  const statePath = harness.managedStatePath(syncEnv.managedStateHome);
  const cleanupEntryNames = new Set<string>();
  for (const name of currentEntryNames) {
    cleanupEntryNames.add(name);
  }
  for (const name of harness.compatManagedEntries) {
    cleanupEntryNames.add(name);
  }
  for (const name of loadRecordedEntryNames(statePath)) {
    cleanupEntryNames.add(name);
  }

  const harnessRoot = harness.root();
  return {
    statePath,
    cleanupPaths: [...cleanupEntryNames]
      .map((entry) => cleanupPath(harnessRoot, entry))
      .filter((entry): entry is string => entry !== null),
    currentEntryNames,
  };
}

function currentManagedEntryNames(syncEnv: SyncEnv, harness: Harness): string[] {
  const names = new Set<string>();
  names.add(harness.instructionFileName());
  for (const entryName of topLevelEntryNames(harness.sourceRoot(syncEnv.toolsHome))) {
    names.add(entryName);
  }
  for (const assetName of assetDirNames(syncEnv.assetsHome)) {
    names.add(harness.renameAsset(assetName));
  }
  return [...names].sort();
}

function cleanupPath(root: string, entryName: string): string | null {
  const safeName = safeTopLevelEntryName(entryName);
  return safeName ? join(root, safeName) : null;
}

function safeTopLevelEntryName(entryName: string): string | null {
  if (entryName.length === 0) {
    return null;
  }
  if (posix.isAbsolute(entryName)) {
    return null;
  }
  if (entryName.includes("/")) {
    return null;
  }
  if (entryName === "." || entryName === "..") {
    return null;
  }
  return entryName;
}

function createTempStateFile(path: string): { tempPath: string; fd: number } {
  const baseName = path.split("/").pop() ?? "managed-state.json";
  const nonce = Date.now().toString(16);
  for (let attempt = 0; attempt < 16; attempt += 1) {
    const tempPath = join(dirname(path), `.${baseName}.${process.pid}.${nonce}-${attempt}.tmp`);
    try {
      const fd = fs.openSync(tempPath, "wx");
      return { tempPath, fd };
    } catch (error) {
      if (!isAlreadyExists(error)) {
        throw new Error(`create ${tempPath} (${panicMessage(error)})`);
      }
    }
  }

  throw new Error(`create temporary managed state near ${path} (name collision)`);
}

function isDirectory(path: string): boolean {
  try {
    return fs.statSync(path).isDirectory();
  } catch {
    return false;
  }
}

function isNotFound(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && (error as { code?: string }).code === "ENOENT";
}

function isAlreadyExists(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && (error as { code?: string }).code === "EEXIST";
}
