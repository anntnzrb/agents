import { Effect, Option } from "effect"

import { joinPath } from "#domain/PathText"
import { fastForwardSsot, readSyncedCommit, recordSyncedCommit } from "#jobs/Update"
import { Lock } from "#platform/Lock"
import { rerunInCurrentRuntime, runtimeRelease, shouldHandOff } from "#programs/Handoff"
import { runSyncWithDeadline } from "#programs/RunSync"
import { Output } from "#services/Output"
import { SyncEnv } from "#services/SyncEnv"

export const update = Effect.fn("Update.update")(function* () {
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
        return { code: 0, handOff: false }
      }
      const head = yield* fastForwardSsot(env.paths.ssotHome)
      if (head === null || head === (yield* readSyncedCommit(env.paths.managedStateHome))) {
        return { code: 0, handOff: false }
      }
      const before = yield* runtimeRelease(env)
      const code = yield* runSyncWithDeadline(env)
      if (code !== 0) {
        return { code, handOff: false }
      }
      const after = yield* runtimeRelease(env)
      if (after === before) {
        yield* recordSyncedCommit(env.paths.managedStateHome, head)
        return { code, handOff: false }
      }
      if (yield* shouldHandOff(env, before)) {
        return { code, handOff: true }
      }
      yield* output.warn("update: sync runtime changed; reconciling again on the next run")
      return { code, handOff: false }
    }),
  )
  return outcome.handOff ? yield* rerunInCurrentRuntime(env, "update") : outcome.code
})
