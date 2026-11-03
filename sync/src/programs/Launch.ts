import { Array as Arr, Effect, FileSystem, Option } from "effect"

import { supportedHarness } from "#domain/Harness"
import { joinPath } from "#domain/PathText"
import { toolLauncher, toolLauncherDefaultArgs } from "#domain/ToolLaunchers"
import { harnessHasCache, launchHarness, launchNpmPackage } from "#packages/Launch"
import { currentCachedPackage } from "#packages/NpmCache"
import { Exec } from "#platform/Exec"
import { Lock } from "#platform/Lock"
import { rerunInCurrentRuntime, runtimeRelease, shouldHandOff } from "#programs/Handoff"
import { runSyncWithDeadline } from "#programs/RunSync"
import { Output } from "#services/Output"
import { SyncEnv } from "#services/SyncEnv"

const detail = (error: unknown): string => (error instanceof Error ? error.message : String(error))

const syncBeforeLaunch = Effect.fn("Launch.syncBeforeLaunch")(function* () {
  const env = yield* SyncEnv
  const lock = yield* Lock
  const output = yield* Output
  const outcome = yield* Effect.scoped(
    Effect.gen(function* () {
      const acquired = yield* lock
        .tryAcquireSyncLock(env.paths.managedStateHome, joinPath(env.paths.managedStateHome, "sync.lock"))
        .pipe(Effect.result)
      if (acquired._tag === "Failure") {
        yield* output.warn(`sync before launch unavailable: ${detail(acquired.failure)}`)
        return { code: 0, handOff: false }
      }
      if (Option.isNone(acquired.success)) {
        yield* output.warn("another sync is already running; continuing launch")
        return { code: 0, handOff: false }
      }
      const before = yield* runtimeRelease(env)
      const code = yield* runSyncWithDeadline(env)
      if (code === 124) {
        yield* output.warn("sync before launch timed out; continuing launch")
      } else if (code !== 0) {
        yield* output.warn("continuing launch without completed sync")
      }
      return { code: 0, handOff: code === 0 && (yield* shouldHandOff(env, before)) }
    }),
  )
  if (outcome.handOff && (yield* rerunInCurrentRuntime(env)) !== 0) {
    yield* output.warn("continuing launch without completed sync")
  }
  return outcome.code
})

// A discovered harness wins; otherwise an installed harness is usable when the SSOT
// is unavailable or its package is already cached; otherwise try the tool launchers.
const resolveTarget = Effect.fn("Launch.resolveTarget")(function* (name: string, available: boolean) {
  const env = yield* SyncEnv
  const discovered = Option.getOrUndefined(Arr.findFirst(env.harnesses, (item) => item.sourceName === name))
  if (discovered !== undefined) {
    return { harness: discovered, tool: undefined }
  }
  const installed = supportedHarness(env.paths.home, name, env.platform)
  if (installed !== undefined && (!available || (yield* harnessHasCache(env.paths.home, installed)))) {
    return { harness: installed, tool: undefined }
  }
  return { harness: undefined, tool: toolLauncher(name) }
})

export const launch = Effect.fn("Launch.launch")(function* (name: string, args: readonly string[]) {
  const env = yield* SyncEnv
  const fs = yield* FileSystem.FileSystem
  const output = yield* Output
  const exec = yield* Exec
  const available = yield* fs.exists(env.paths.ssotHome)
  const { harness, tool } = yield* resolveTarget(name, available)
  if (harness === undefined && tool === undefined) {
    yield* output.err(`unsupported launch target: ${name}`)
    return 2
  }
  const launchEnv = { home: env.paths.home, rootEnv: env.rootEnv, installTimeoutMs: env.installTimeoutMs }
  const spec = tool === undefined ? undefined : { tool: tool.id, package: tool.package, bin: tool.bin }
  const result = yield* Effect.gen(function* () {
    const cachedPackage =
      spec === undefined ? Option.none() : yield* currentCachedPackage(spec, { home: env.paths.home })
    const cached =
      spec === undefined
        ? harness !== undefined && (yield* harnessHasCache(env.paths.home, harness))
        : Option.isSome(cachedPackage)
    if (!cached) {
      yield* available
        ? syncBeforeLaunch()
        : output.warn("agent configuration source is unavailable; continuing with installed runtime")
    }
    if (spec !== undefined && tool !== undefined) {
      const plan = yield* launchNpmPackage(launchEnv, spec, [
        ...toolLauncherDefaultArgs(launchEnv, tool),
        ...args,
      ])
      return yield* exec.exec(plan)
    }
    if (harness !== undefined) {
      const plan = yield* launchHarness(launchEnv, harness, [...harness.launcher.defaultArgs, ...args])
      return yield* exec.exec(plan)
    }
    return 2
  }).pipe(Effect.result)
  if (result._tag === "Failure") {
    if (result.failure._tag === "DeadlineCleanupOverrun") {
      return yield* result.failure
    }
    yield* output.err(`launch failed: ${detail(result.failure)}`)
    return 1
  }
  return result.success
})
