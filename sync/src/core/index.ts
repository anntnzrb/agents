import path from "node:path";

import { Effect } from "effect";

import { SyncEnv } from "./harness.ts";
import {
  clearExtensionHookState,
  prepareExtensionHookState,
  recordExtensionHookState,
  type PreparedExtensionHookState,
} from "./hook-state.ts";
import { installExtensionDeps } from "../extensions/install.ts";
import { runJobsWithPreserve } from "./jobs.ts";
import {
  cleanManagedEntries,
  planManagedEntriesForSyncPlan,
  recordManagedEntries,
} from "./managed-state.ts";
import { bootstrapPackageTarget } from "../packages/index.ts";
import { buildSyncPlan, type SyncHookPlan } from "./plan.ts";
export { copyTree, isSymlink, rmEntry } from "../runtime/fs.ts";
import { panicMessage } from "../runtime/errors.ts";
import {
  releaseSyncLock as releaseSyncLockImpl,
  type SyncLock,
  tryAcquireSyncLock as tryAcquireSyncLockImpl,
} from "../runtime/lock.ts";

const SYNC_TIMEOUT_ENV = "AGENTS_SYNC_TIMEOUT_SECONDS";
const DEFAULT_SYNC_TIMEOUT_SECONDS = 15 * 60;
const SYNC_LOCK_FILE = "sync.lock";

export type { SyncLock } from "../runtime/lock.ts";

export function err(message: string): void {
  console.error(`sync: ${message}`);
}

export function warn(message: string): void {
  console.error(`sync: warning: ${message}`);
}
export { panicMessage } from "../runtime/errors.ts";

export function parseTimeoutSeconds(value: string | undefined, defaultSeconds: number): number {
  const parsed = value ? Number.parseInt(value, 10) : Number.NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : defaultSeconds;
}

export function syncTimeout(): number {
  return parseTimeoutSeconds(process.env[SYNC_TIMEOUT_ENV], DEFAULT_SYNC_TIMEOUT_SECONDS);
}

export function syncLockPath(syncEnv: SyncEnv): string {
  return path.join(syncEnv.managedStateHome, SYNC_LOCK_FILE);
}

export function tryAcquireSyncLock(syncEnv: SyncEnv): SyncLock | undefined {
  return tryAcquireSyncLockImpl(syncEnv.managedStateHome, syncLockPath(syncEnv));
}

export function startSyncWatchdog(timeoutSeconds: number): void {
  const timer = setTimeout(() => {
    err(`timed out after ${timeoutSeconds}s`);
    process.exit(124);
  }, timeoutSeconds * 1000);
  timer.unref();
}

export async function runSync(syncEnv: SyncEnv): Promise<boolean> {
  let syncPlan;
  let managedPlan;
  let extensionHookStates;
  try {
    syncPlan = buildSyncPlan(syncEnv);
    managedPlan = planManagedEntriesForSyncPlan(syncPlan);
    extensionHookStates = prepareExtensionHookStates(syncPlan.hooks);
  } catch (error) {
    err(panicMessage(error));
    return false;
  }

  const cleanupSuccess = cleanManagedEntries(managedPlan);
  const baseSuccess = cleanupSuccess
    ? (() => {
        try {
          return runJobsWithPreserve(syncPlan.jobs, preservePathsByDst(extensionHookStates));
        } catch (error) {
          err(panicMessage(error));
          return false;
        }
      })()
    : false;

  const managedStateSuccess = baseSuccess ? recordManagedEntries(managedPlan) : true;
  const hookSuccess =
    baseSuccess && managedStateSuccess
      ? await runSyncHooks(syncPlan.hooks, extensionHookStates)
      : true;

  return baseSuccess && managedStateSuccess && hookSuccess;
}

export const main = (): Effect.Effect<number> =>
  Effect.gen(function* () {
    const syncEnvResult = yield* Effect.either(
      Effect.try({
        try: () => SyncEnv.fromSystem(),
        catch: (error) => panicMessage(error),
      }),
    );
    if (syncEnvResult._tag === "Left") {
      yield* logErr(syncEnvResult.left);
      return 1;
    }
    const syncEnv = syncEnvResult.right;

    return yield* Effect.scoped(
      Effect.gen(function* () {
        const lockResult = yield* Effect.either(
          Effect.acquireRelease(
            Effect.try({
              try: () => tryAcquireSyncLock(syncEnv),
              catch: (error) => panicMessage(error),
            }),
            (lock) =>
              Effect.sync(() => {
                if (lock) {
                  releaseSyncLockImpl(lock);
                }
              }),
          ),
        );

        if (lockResult._tag === "Left") {
          yield* logErr(lockResult.left);
          return 1;
        }
        if (!lockResult.right) {
          yield* logErr("another sync is already running; skipping");
          return 0;
        }

        startSyncWatchdog(syncTimeout());
        const success = yield* Effect.promise(() => runSync(syncEnv));
        return success ? 0 : 1;
      }),
    );
  });

async function runSyncHooks(
  hooks: readonly SyncHookPlan[],
  extensionHookStates: ReadonlyMap<string, ExtensionHookRuntimeState>,
): Promise<boolean> {
  let success = true;
  for (const hook of hooks) {
    const hookState =
      hook.kind === "ExtensionDeps" ? extensionHookStates.get(hook.statePath)?.state : undefined;
    if (!(await runSyncHook(hook, hookState))) {
      success = false;
    }
  }
  return success;
}

async function runSyncHook(
  hook: SyncHookPlan,
  extensionHookState?: PreparedExtensionHookState,
): Promise<boolean> {
  try {
    switch (hook.kind) {
      case "PackageBootstrap":
        return await bootstrapPackageTarget(hook);
      case "ExtensionDeps": {
        if (extensionHookState?.shouldSkip) {
          return true;
        }
        const success = await Effect.runPromise(installExtensionDeps(hook.root, hook.timeoutMs));
        if (success) {
          recordExtensionHookState(hook, extensionHookState ?? prepareExtensionHookState(hook));
        } else {
          clearExtensionHookState(hook.statePath);
        }
        return success;
      }
    }
  } catch (error) {
    if (hook.kind === "ExtensionDeps") {
      clearExtensionHookState(hook.statePath);
    }
    err(panicMessage(error));
    return false;
  }
}

function logErr(message: string): Effect.Effect<void> {
  return Effect.sync(() => err(message));
}

function prepareExtensionHookStates(
  hooks: readonly SyncHookPlan[],
): ReadonlyMap<string, ExtensionHookRuntimeState> {
  const states = new Map<string, ExtensionHookRuntimeState>();
  for (const hook of hooks) {
    if (hook.kind !== "ExtensionDeps") {
      continue;
    }
    states.set(hook.statePath, {
      hook,
      state: prepareExtensionHookState(hook),
    });
  }
  return states;
}

function preservePathsByDst(
  states: ReadonlyMap<string, ExtensionHookRuntimeState>,
): ReadonlyMap<string, readonly string[]> {
  const preserveByDst = new Map<string, string[]>();
  for (const { hook, state } of states.values()) {
    if (!state.shouldSkip || state.preservePaths.length === 0) {
      continue;
    }
    const paths = preserveByDst.get(hook.jobRoot) ?? [];
    paths.push(...state.preservePaths);
    preserveByDst.set(hook.jobRoot, [...new Set(paths)].sort());
  }
  return preserveByDst;
}

interface ExtensionHookRuntimeState {
  readonly hook: Extract<SyncHookPlan, { readonly kind: "ExtensionDeps" }>;
  readonly state: PreparedExtensionHookState;
}
