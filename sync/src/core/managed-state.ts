import fs from "node:fs";
import { basename, dirname, join } from "node:path";
import { err, isErrno, panicMessage, warn } from "@runtime/errors.ts";
import { rmEntry } from "@runtime/fs.ts";

import type { SyncEnv } from "./harness.ts";
import { buildSyncPlan, isSafeManagedEntryName, type SyncPlan } from "./plan.ts";

export interface ManagedSyncPlan {
  harnesses: ManagedHarnessPlan[];
}

export interface ManagedHarnessPlan {
  statePath: string;
  cleanupPaths: string[];
  currentEntryNames: string[];
}

export function planManagedEntries(syncEnv: SyncEnv): ManagedSyncPlan {
  return planManagedEntriesForSyncPlan(buildSyncPlan(syncEnv));
}

export function planManagedEntriesForSyncPlan(syncPlan: SyncPlan): ManagedSyncPlan {
  return {
    harnesses: syncPlan.harnesses.map((harnessPlan) => {
      const currentEntryNames = [...harnessPlan.currentEntryNames];
      const currentEntrySet = new Set(currentEntryNames);
      const staleEntryNames = uniqueSorted([
        ...harnessPlan.cleanupEntryNames,
        ...loadRecordedEntryNames(harnessPlan.statePath),
      ]).filter((entryName) => !currentEntrySet.has(entryName));
      return {
        statePath: harnessPlan.statePath,
        cleanupPaths: staleEntryNames
          .map((entry) => cleanupPath(harnessPlan.root, entry))
          .filter((entry): entry is string => entry !== null),
        currentEntryNames,
      };
    }),
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

export { topLevelEntryNames } from "./plan.ts";

export function loadRecordedEntryNames(path: string): string[] {
  let content: string;
  try {
    content = fs.readFileSync(path, "utf8");
  } catch (error) {
    if (isErrno(error, "ENOENT")) {
      return [];
    }
    throw new Error(`read ${path} (${panicMessage(error)})`, { cause: error });
  }

  let parsed: unknown;
  try {
    parsed = Bun.JSONC.parse(content);
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
    if (isSafeManagedEntryName(entryName)) {
      safeNames.add(entryName);
    } else {
      warn(`ignoring unsafe managed entry ${JSON.stringify(entryName)} in ${path}`);
    }
  }
  return [...safeNames].toSorted();
}

export function writeRecordedEntryNames(path: string, entryNames: string[]): void {
  const parent = dirname(path);
  try {
    fs.mkdirSync(parent, { recursive: true });
  } catch (error) {
    throw new Error(`create ${parent} (${panicMessage(error)})`, { cause: error });
  }

  let content: string;
  try {
    content = `${JSON.stringify(entryNames, null, 2)}\n`;
  } catch (error) {
    throw new Error(`serialize ${path} (${panicMessage(error)})`, { cause: error });
  }
  try {
    const existing = fs.lstatSync(path);
    if (existing.isFile() && fs.readFileSync(path, "utf8") === content) {
      return;
    }
  } catch (error) {
    if (!isErrno(error, "ENOENT")) {
      throw new Error(`read ${path} (${panicMessage(error)})`, { cause: error });
    }
  }
  const { tempPath, fd } = createTempStateFile(path);
  try {
    try {
      fs.writeFileSync(fd, content, "utf8");
    } catch (error) {
      throw new Error(`write ${tempPath} (${panicMessage(error)})`, { cause: error });
    }
    try {
      fs.fsyncSync(fd);
    } catch (error) {
      throw new Error(`sync ${tempPath} (${panicMessage(error)})`, { cause: error });
    }
    try {
      fs.closeSync(fd);
    } catch {
      // ignore
    }
    try {
      fs.renameSync(tempPath, path);
    } catch (error) {
      throw new Error(`replace ${path} (${panicMessage(error)})`, { cause: error });
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

function cleanupPath(root: string, entryName: string): string | null {
  const safeName = isSafeManagedEntryName(entryName) ? entryName : null;
  return safeName ? join(root, safeName) : null;
}

function createTempStateFile(path: string): { tempPath: string; fd: number } {
  const baseName = basename(path) || "managed-state.json";
  const nonce = Date.now().toString(16);
  for (let attempt = 0; attempt < 16; attempt += 1) {
    const tempPath = join(dirname(path), `.${baseName}.${process.pid}.${nonce}-${attempt}.tmp`);
    try {
      const fd = fs.openSync(tempPath, "wx");
      return { tempPath, fd };
    } catch (error) {
      if (!isErrno(error, "EEXIST")) {
        throw new Error(`create ${tempPath} (${panicMessage(error)})`, { cause: error });
      }
    }
  }

  throw new Error(`create temporary managed state near ${path} (name collision)`);
}

const uniqueSorted = (names: readonly string[]): string[] => [...new Set(names)].toSorted();
