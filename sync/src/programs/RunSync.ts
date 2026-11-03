import { Array as Arr, Effect, Fiber, Option, Order, Schema } from "effect"

import { joinPath } from "#domain/PathText"
import type { ExtensionDepsHookPlan } from "#domain/Plan"
import type { PreparedHookState } from "#domain/State"
import { installExtensionDeps } from "#jobs/ExtensionDeps"
import { ensurePythonEnv } from "#jobs/PythonEnv"
import { runJobsWithPreserve } from "#jobs/RunJobs"
import { pruneUnreferencedReleases } from "#jobs/RuntimeRelease"
import { reconcileWrappers } from "#jobs/Wrappers"
import { Lock } from "#platform/Lock"
import { rerunInCurrentRuntime, runtimeRelease, shouldHandOff } from "#programs/Handoff"
import {
  clearExtensionHookState,
  prepareExtensionHookState,
  recordExtensionHookState,
} from "#services/HookState"
import {
  cleanManagedEntries,
  planManagedEntriesForSyncPlan,
  recordManagedEntries,
} from "#services/ManagedState"
import { Output } from "#services/Output"
import { buildSyncPlan } from "#services/Planner"
import { SyncEnv } from "#services/SyncEnv"
import type { SyncEnvValue } from "#services/SyncEnv"

export class DeadlineCleanupOverrun extends Schema.TaggedError<
  DeadlineCleanupOverrun,
  { readonly brand: unique symbol }
>()("DeadlineCleanupOverrun", {}) {}

interface HookRuntimeState {
  readonly hook: ExtensionDepsHookPlan
  readonly state: PreparedHookState
}

export const prepareExtensionHookStates = Effect.fn("RunSync.prepareExtensionHookStates")(function* (
  hooks: readonly ExtensionDepsHookPlan[],
) {
  const states = new Map<string, HookRuntimeState>()
  const fingerprints = new Map<string, string>()
  for (const hook of hooks) {
    const state = yield* prepareExtensionHookState(hook, fingerprints.get(hook.sourceRoot))
    fingerprints.set(hook.sourceRoot, state.fingerprint)
    states.set(hook.statePath, { hook, state })
  }
  return states
})

export const preservePathsByDst = (states: ReadonlyMap<string, HookRuntimeState>) => {
  const preserved = new Map<string, readonly string[]>()
  for (const { hook, state } of states.values()) {
    if (state.shouldSkip && state.preservePaths.length > 0) {
      const merged = new Set([...(preserved.get(hook.jobRoot) ?? []), ...state.preservePaths])
      preserved.set(hook.jobRoot, Arr.sort([...merged], Order.String))
    }
  }
  return preserved
}

export const runSyncHook = Effect.fn("RunSync.runSyncHook")(function* (
  hook: ExtensionDepsHookPlan,
  state: PreparedHookState,
) {
  const output = yield* Output
  return yield* Effect.gen(function* () {
    if (state.shouldSkip) {
      if (state.shouldRefreshState) {
        yield* recordExtensionHookState(hook, state)
      }
      return true
    }
    const success = yield* installExtensionDeps(hook.root, hook.sourceRoot, hook.timeoutMs)
    yield* success ? recordExtensionHookState(hook, state) : clearExtensionHookState(hook.statePath)
    return success
  }).pipe(
    Effect.catch((error) =>
      Effect.gen(function* () {
        yield* clearExtensionHookState(hook.statePath)
        yield* output.err(error instanceof Error ? error.message : String(error))
        return false
      }),
    ),
  )
})

export const runSync = Effect.fn("RunSync.runSync")(function* (env: SyncEnvValue) {
  const plan = yield* buildSyncPlan(env)
  const managed = yield* planManagedEntriesForSyncPlan(
    { home: env.paths.home, managedStateHome: env.paths.managedStateHome, platform: env.platform },
    plan,
  )
  const hooks = yield* prepareExtensionHookStates(plan.hooks)
  for (const harness of plan.harnesses) {
    const segments = harness.harness.pythonEnvSegments
    if (segments !== null) {
      yield* ensurePythonEnv(env.paths.home, segments, env.installTimeoutMs)
    }
  }
  if (!(yield* cleanManagedEntries(managed))) {
    return false
  }
  if (!(yield* runJobsWithPreserve(plan.jobs, preservePathsByDst(hooks)))) {
    return false
  }
  const output = yield* Output
  const wrappers = yield* reconcileWrappers({ ...env.paths, harnesses: env.harnesses }).pipe(Effect.result)
  if (wrappers._tag === "Failure") {
    yield* output.err(`wrapper reconciliation failed: ${wrappers.failure.message}`)
    return false
  }
  yield* pruneUnreferencedReleases(
    joinPath(env.paths.runtimeHome, "sync-releases"),
    joinPath(env.paths.runtimeHome, "sync-current"),
    env.installTimeoutMs,
  )
  if (!(yield* recordManagedEntries(managed))) {
    return false
  }
  let success = true
  for (const hook of plan.hooks) {
    const prepared = hooks.get(hook.statePath)
    if (prepared !== undefined) {
      const result = yield* runSyncHook(hook, prepared.state)
      success = result && success
    }
  }
  return success
})

// The 15-minute budget interrupts the sync fiber and allows 30 seconds for scoped
// cleanup (process-group kills, stage removal) before giving up on it. An external
// interruption (SIGINT/SIGTERM via runMain) gets the same cleanup window.
export const runSyncWithDeadline = Effect.fn("RunSync.runSyncWithDeadline")(function* (env: SyncEnvValue) {
  const output = yield* Output
  const fiber = yield* Effect.forkDetach(runSync(env))
  const interruptWithGrace = Fiber.interrupt(fiber).pipe(Effect.timeoutOption("30 seconds"))
  const completed = yield* Fiber.await(fiber).pipe(
    Effect.timeoutOption("15 minutes"),
    Effect.onInterrupt(() => interruptWithGrace),
  )
  if (Option.isSome(completed)) {
    return (yield* Fiber.join(fiber)) ? 0 : 1
  }
  yield* output.err("timed out after 900s")
  const finished = yield* interruptWithGrace
  if (Option.isNone(finished)) {
    return yield* DeadlineCleanupOverrun.make({})
  }
  return 124
})

export const syncMain = Effect.fn("RunSync.syncMain")(function* () {
  const env = yield* SyncEnv
  const lock = yield* Lock
  const output = yield* Output
  const outcome = yield* Effect.scoped(
    Effect.gen(function* () {
      const acquired = yield* lock.tryAcquireSyncLock(
        env.paths.managedStateHome,
        joinPath(env.paths.managedStateHome, "sync.lock"),
      )
      if (Option.isNone(acquired)) {
        yield* output.err("another sync is already running; skipping")
        return { code: 0, handOff: false }
      }
      const before = yield* runtimeRelease(env)
      const code = yield* runSyncWithDeadline(env)
      return { code, handOff: code === 0 && (yield* shouldHandOff(env, before)) }
    }),
  )
  return outcome.handOff ? yield* rerunInCurrentRuntime(env) : outcome.code
})
