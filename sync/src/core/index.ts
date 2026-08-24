import { existsSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { installExtensionDeps } from "@extensions/install.ts";
import { bootstrapPackageTarget } from "@packages/index.ts";
import { SyncEnv, supportedHarness } from "./harness.ts";
import {
  clearExtensionHookState,
  type PreparedExtensionHookState,
  prepareExtensionHookState,
  recordExtensionHookState,
} from "./hook-state.ts";
import { runJobsWithPreserve } from "./jobs.ts";
import { launchHarness, launchNpmPackage } from "./launcher.ts";
import {
  cleanManagedEntries,
  type ManagedSyncPlan,
  planManagedEntriesForSyncPlan,
  recordManagedEntries,
} from "./managed-state.ts";
import {
  isCliProxyRunning,
  type PreparedManagedTool,
  prepareManagedTools,
} from "./managed-tools.ts";
import { buildSyncPlan, type SyncHookPlan, type SyncPlan } from "./plan.ts";
import { toolLauncher } from "./tool-launchers.ts";
import { managedToolWrapperDestination, reconcileWrappers } from "./wrappers.ts";

export { copyTree, isSymlink, rmEntry } from "@runtime/fs.ts";

import { assertNever, err, panicMessage, warn } from "@runtime/errors.ts";
import {
  releaseSyncLock as releaseSyncLockImpl,
  type SyncLock,
  tryAcquireSyncLock as tryAcquireSyncLockImpl,
} from "@runtime/lock.ts";

const DEFAULT_SYNC_TIMEOUT_SECONDS = 15 * 60;
const SYNC_LOCK_FILE = "sync.lock";

export type { SyncLock } from "@runtime/lock.ts";

async function ensurePythonEnv(home = homedir()): Promise<void> {
  const venvPython = path.join(home, ".omp", "python-env", "bin", "python");
  if (existsSync(venvPython)) {
    return;
  }

  if (!Bun.which("uv")) {
    warn("uv not found; skipping python-env bootstrap.");
    return;
  }

  const install = Bun.spawnSync(["uv", "python", "install"]);
  if (!install.success) {
    warn("uv python install failed; skipping.");
    return;
  }

  const find = Bun.spawnSync(["uv", "python", "find"], { stdout: "pipe" });
  const latest = find.stdout?.toString().trim();
  if (!latest) {
    warn("uv python find returned empty; skipping.");
    return;
  }

  const venv = Bun.spawnSync([
    "uv",
    "venv",
    "--python",
    latest,
    path.join(homedir(), ".omp", "python-env"),
  ]);
  if (!venv.success) {
    warn("failed to create python-env");
  }
}

export { err, panicMessage, warn } from "@runtime/errors.ts";

export function parseTimeoutSeconds(value: string | undefined, defaultSeconds: number): number {
  const parsed = value ? Number.parseInt(value, 10) : Number.NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : defaultSeconds;
}

export const syncTimeout = (): number => DEFAULT_SYNC_TIMEOUT_SECONDS;

export const syncLockPath = (syncEnv: SyncEnv): string =>
  path.join(syncEnv.managedStateHome, SYNC_LOCK_FILE);

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

export async function runSync(
  syncEnv: SyncEnv,
  options: {
    readonly warnManagedServices?: boolean;
    readonly forceModelRefresh?: boolean;
  } = {},
): Promise<boolean> {
  let syncPlan: SyncPlan;
  let managedPlan: ManagedSyncPlan;
  let extensionHookStates: ReadonlyMap<string, ExtensionHookRuntimeState>;
  try {
    syncPlan = buildSyncPlan(syncEnv);
    managedPlan = planManagedEntriesForSyncPlan(syncPlan);
    extensionHookStates = prepareExtensionHookStates(syncPlan.hooks);
  } catch (error) {
    err(panicMessage(error));
    return false;
  }

  const cleanupSuccess = cleanManagedEntries(managedPlan);
  let baseSuccess = false;
  if (cleanupSuccess) {
    try {
      baseSuccess = await runJobsWithPreserve(
        syncPlan.jobs,
        preservePathsByDst(extensionHookStates),
        {
          ...(options.forceModelRefresh === undefined
            ? {}
            : { forceModelRefresh: options.forceModelRefresh }),
          quietModelRefresh: !options.warnManagedServices,
        },
      );
    } catch (error) {
      err(panicMessage(error));
    }
  }

  let managedTools: PreparedManagedTool[] = [];
  let managedToolSuccess = baseSuccess;
  if (baseSuccess && syncPlan.gatewayHost) {
    try {
      managedTools = [...(await prepareManagedTools(syncEnv))];
    } catch (error) {
      err(panicMessage(error));
      managedToolSuccess = false;
    }
  }

  const wrapperSuccess = managedToolSuccess
    ? reconcileWrappers(syncEnv, {
        additionalDestinations: managedTools.map((tool) =>
          managedToolWrapperDestination(syncEnv, tool),
        ),
      })
    : false;

  const managedStateSuccess =
    baseSuccess && wrapperSuccess ? recordManagedEntries(managedPlan) : true;
  const hookSuccess =
    baseSuccess && wrapperSuccess && managedStateSuccess
      ? await runSyncHooks(syncPlan.hooks, extensionHookStates)
      : true;

  const success =
    baseSuccess && managedToolSuccess && wrapperSuccess && managedStateSuccess && hookSuccess;
  if (
    success &&
    options.warnManagedServices &&
    managedTools.some((tool) => tool.name === "cliproxyapi") &&
    !(await isCliProxyRunning(syncPlan.cliProxyDeployment))
  ) {
    warn("CLIProxyAPI is installed but not running; start it with: cli-proxy-api");
  }
  return success;
}

export const main = async (
  options: { readonly forceModelRefresh?: boolean } = {},
): Promise<number> => {
  let syncEnv: SyncEnv;
  try {
    syncEnv = SyncEnv.fromSystem();
  } catch (error) {
    err(panicMessage(error));
    return 1;
  }
  await ensurePythonEnv();

  let lock: SyncLock | undefined;
  try {
    lock = tryAcquireSyncLock(syncEnv);
  } catch (error) {
    err(panicMessage(error));
    return 1;
  }

  if (!lock) {
    err("another sync is already running; skipping");
    return 0;
  }

  try {
    startSyncWatchdog(syncTimeout());
    const success = await runSync(syncEnv, {
      warnManagedServices: true,
      ...(options.forceModelRefresh === undefined
        ? {}
        : { forceModelRefresh: options.forceModelRefresh }),
    });
    return success ? 0 : 1;
  } finally {
    releaseSyncLockImpl(lock);
  }
};

/**
 * Wrapper entrypoint: reconcile config first, then hand control to the
 * selected harness or tool. Sync failures are soft here so an unavailable
 * network or broken optional hook cannot strand an otherwise cached binary.
 */
export const launchMain = async (sourceName: string, args: readonly string[]): Promise<number> => {
  let syncEnv: SyncEnv;
  try {
    syncEnv = SyncEnv.fromSystem();
  } catch (error) {
    err(panicMessage(error));
    return 1;
  }

  await ensurePythonEnv();
  const ssotAvailable = existsSync(syncEnv.ssotHome);
  const harness =
    syncEnv.harnesses.find((candidate) => candidate.sourceName === sourceName) ??
    (ssotAvailable ? undefined : supportedHarness(syncEnv.home, sourceName, syncEnv.platform));
  const tool = harness ? undefined : toolLauncher(sourceName);
  if (!harness && !tool) {
    err(`unsupported launch target: ${sourceName}`);
    return 2;
  }

  if (ssotAvailable) {
    let lock: SyncLock | undefined;
    try {
      lock = tryAcquireSyncLock(syncEnv);
    } catch (error) {
      warn(`sync before launch unavailable: ${panicMessage(error)}`);
    }

    if (lock) {
      try {
        const success = await runSync(syncEnv);
        if (!success) {
          warn("continuing launch without completed sync");
        }
      } finally {
        releaseSyncLockImpl(lock);
      }
    } else {
      warn("another sync is already running; continuing launch");
    }
  } else {
    warn("agent configuration source is unavailable; continuing with installed runtime");
  }

  try {
    if (tool) {
      return await launchNpmPackage(
        syncEnv,
        {
          tool: tool.id,
          package: tool.package,
          bin: tool.bin,
          ...(tool.distTag === undefined ? {} : { distTag: tool.distTag }),
          ...(tool.smokeCheck === undefined ? {} : { smokeCheck: tool.smokeCheck }),
        },
        args,
      );
    }
    return await launchHarness(syncEnv, harness ?? unsupported(), args);
  } catch (error) {
    err(`launch failed: ${panicMessage(error)}`);
    return 1;
  }
};

const unsupported = (): never => {
  throw new Error("unreachable: launch target checked above");
};

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
          if (extensionHookState.shouldRefreshState) {
            recordExtensionHookState(hook, extensionHookState);
          }
          return true;
        }
        const success = await installExtensionDeps(hook.root, hook.sourceRoot, hook.timeoutMs);
        if (success) {
          recordExtensionHookState(hook, extensionHookState ?? prepareExtensionHookState(hook));
        } else {
          clearExtensionHookState(hook.statePath);
        }
        return success;
      }
      default:
        return assertNever(hook);
    }
  } catch (error) {
    if (hook.kind === "ExtensionDeps") {
      clearExtensionHookState(hook.statePath);
    }
    err(panicMessage(error));
    return false;
  }
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
    preserveByDst.set(hook.jobRoot, [...new Set(paths)].toSorted());
  }
  return preserveByDst;
}

interface ExtensionHookRuntimeState {
  readonly hook: Extract<SyncHookPlan, { readonly kind: "ExtensionDeps" }>;
  readonly state: PreparedExtensionHookState;
}
