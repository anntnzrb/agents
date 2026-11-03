import { Effect, FileSystem } from "effect"

import { joinPath } from "#domain/PathText"
import { Host } from "#platform/Host"
import { Proc } from "#platform/Proc"
import { Output } from "#services/Output"
import type { SyncEnvValue } from "#services/SyncEnv"

const HANDOFF_ENV = "AGENTS_SYNC_HANDOFF"

/** The release the `sync-current` link points at, or null when it is absent. */
export const runtimeRelease = Effect.fn("Handoff.runtimeRelease")(function* (env: SyncEnvValue) {
  const fs = yield* FileSystem.FileSystem
  return yield* fs
    .readLink(joinPath(env.paths.runtimeHome, "sync-current"))
    .pipe(Effect.orElseSucceed(() => null))
})

/**
 * True when this run published a runtime the process is not running. The first
 * install has no previous runtime, and a handed-off process never hands off again.
 */
export const shouldHandOff = Effect.fn("Handoff.shouldHandOff")(function* (
  env: SyncEnvValue,
  before: string | null,
) {
  const host = yield* Host
  const handedOff = (host.env[HANDOFF_ENV] ?? "") !== ""
  if (before === null || handedOff) {
    return false
  }
  const after = yield* runtimeRelease(env)
  return after !== before
})

/** Run sync again under the newly published runtime; the caller must have released the sync lock. */
export const rerunInCurrentRuntime = Effect.fn("Handoff.rerunInCurrentRuntime")(function* (
  env: SyncEnvValue,
  ...args: string[]
) {
  const output = yield* Output
  const proc = yield* Proc
  yield* output.warn("sync runtime changed; reconciling again with the new runtime")
  const runtime = joinPath(env.paths.runtimeHome, "sync-current", "sync")
  return yield* proc
    .runAttached([runtime, ...args], { [HANDOFF_ENV]: "1" })
    .pipe(
      Effect.catchTag("ProcError", (error) =>
        output.err(`rerun with the new runtime failed: ${String(error.cause)}`).pipe(Effect.as(1)),
      ),
    )
})
