import fs from "node:fs";
import { dirname, join } from "node:path";
import { err, isErrno, panicMessage, warn } from "@runtime/errors.ts";
import { rmEntry } from "@runtime/fs.ts";
import { Schema } from "effect";
import { buildHarness, harnessManagedStatePath, harnessRoot, type SyncEnv } from "./harness.ts";
import { HARNESS_ADAPTERS } from "./harness-adapters.ts";
import { buildSyncPlan, isSafeManagedEntryName, type SyncPlan } from "./plan.ts";

const RecordedEntriesSchema = Schema.Array(Schema.String);

export interface ManagedSyncPlan {
  harnesses: ManagedHarnessPlan[];
}

export interface ManagedHarnessPlan {
  statePath: string;
  cleanupPaths: string[];
  currentEntryNames: string[];
  active: boolean;
}

export function planManagedEntries(syncEnv: SyncEnv): ManagedSyncPlan {
  return planManagedEntriesForSyncPlan(syncEnv, buildSyncPlan(syncEnv));
}

export function planManagedEntriesForSyncPlan(
  syncEnv: SyncEnv,
  syncPlan: SyncPlan,
): ManagedSyncPlan {
  const activeIds = new Set(syncPlan.harnesses.map((plan) => plan.harness.id));
  const harnesses: ManagedHarnessPlan[] = syncPlan.harnesses.map((harnessPlan) => {
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
      active: true,
    };
  });

  for (const adapter of HARNESS_ADAPTERS) {
    if (!adapter.platforms.includes(syncEnv.platform)) {
      continue;
    }
    if (activeIds.has(adapter.id)) {
      continue;
    }

    const harness = buildHarness({
      ...adapter,
      id: adapter.id,
      sourceName: adapter.id,
      home: join(syncEnv.home, ...adapter.homeSegments),
    });
    const statePath = harnessManagedStatePath(harness, syncEnv.managedStateHome);
    if (!fs.existsSync(statePath)) {
      continue;
    }

    const root = harnessRoot(harness);
    const recorded = loadRecordedEntryNames(statePath);
    const staleEntryNames = uniqueSorted([...harness.compatManagedEntries, ...recorded]).filter(
      (entryName) => isSafeManagedEntryName(entryName),
    );
    harnesses.push({
      statePath,
      cleanupPaths: staleEntryNames.map((entryName) => join(root, entryName)),
      currentEntryNames: [],
      active: false,
    });
  }

  return { harnesses };
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
    if (!harness.active) {
      try {
        fs.rmSync(harness.statePath, { force: true });
      } catch (error) {
        err(`managed state removal failed: ${harness.statePath} (${panicMessage(error)})`);
        success = false;
      }
      continue;
    }
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
  try {
    const content = fs.readFileSync(path, "utf8");
    const parsed = Schema.decodeUnknownSync(RecordedEntriesSchema)(JSON.parse(content));
    return uniqueSorted(parsed.filter((entry) => isSafeManagedEntryName(entry)));
  } catch (error) {
    if (isErrno(error, "ENOENT")) {
      return [];
    }
    warn(`ignoring malformed managed state ${path} (${panicMessage(error)})`);
    return [];
  }
}

export function writeRecordedEntryNames(path: string, entryNames: string[]): void {
  const payload = `${JSON.stringify(uniqueSorted(entryNames), null, 2)}\n`;
  try {
    const stat = fs.lstatSync(path);
    if (stat.isFile() && !stat.isSymbolicLink() && fs.readFileSync(path, "utf8") === payload) {
      return;
    }
  } catch {
    // missing or unreadable: replace below
  }

  const dir = dirname(path);
  fs.mkdirSync(dir, { recursive: true });
  const temp = `${path}.${process.pid}.tmp`;
  try {
    fs.writeFileSync(temp, payload);
    fs.renameSync(temp, path);
  } catch (error) {
    try {
      fs.rmSync(temp, { force: true });
    } catch {
      // ignore
    }
    throw error;
  }
}

function cleanupPath(root: string, entryName: string): string | null {
  if (!isSafeManagedEntryName(entryName)) {
    warn(`skipping unsafe recorded managed entry name: ${entryName}`);
    return null;
  }
  return join(root, entryName);
}

function uniqueSorted(names: readonly string[]): string[] {
  return [...new Set(names)].toSorted();
}
