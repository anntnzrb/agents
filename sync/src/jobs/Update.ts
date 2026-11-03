import { Array as Arr, Effect, FileSystem, Path, Schema, String as Str } from "effect"

import { SyncedState } from "#domain/State"
import { Files } from "#platform/Files"
import { Proc } from "#platform/Proc"
import { Output } from "#services/Output"

export const SYNCED_STATE_FILE = "update.json"
const GIT_TIMEOUT_MS = 60_000

const git = Effect.fn("Update.git")(function* (home: string, ...args: string[]) {
  const proc = yield* Proc
  const result = yield* proc.run(["git", "-C", home, ...args], { timeoutMs: GIT_TIMEOUT_MS })
  const ok = result.exitCode === 0 && !result.timedOut && !result.outputLimited
  return { ok, text: Str.trim(ok ? result.stdout : result.stderr) }
})

export const fastForwardSsot = Effect.fn("Update.fastForwardSsot")(function* (home: string) {
  const output = yield* Output
  const branch = yield* git(home, "symbolic-ref", "--short", "-q", "HEAD")
  if (!branch.ok || branch.text !== "main") {
    yield* output.warn(
      `update: skipped; checkout is on ${branch.ok ? branch.text : "detached HEAD"}, not main`,
    )
    return null
  }
  const status = yield* git(home, "status", "--porcelain", "--untracked-files=no")
  if (!status.ok) {
    yield* output.warn(`update: skipped; git status failed (${status.text})`)
    return null
  }
  if (status.text !== "") {
    const names = yield* git(home, "diff", "--name-only", "HEAD")
    yield* output.warn(
      `update: skipped; uncommitted tracked changes block pull: ${Arr.join(Str.split(names.text, /\r?\n/u), ", ") || status.text}`,
    )
    return null
  }
  const fetched = yield* git(home, "fetch", "--quiet", "origin", "main")
  if (fetched.ok) {
    const ancestor = yield* git(home, "merge-base", "--is-ancestor", "HEAD", "origin/main")
    if (ancestor.ok) {
      const merged = yield* git(home, "merge", "--ff-only", "--quiet", "origin/main")
      if (!merged.ok) {
        yield* output.warn(`update: fast-forward failed; keeping local checkout (${merged.text})`)
      }
    } else {
      const counts = yield* git(home, "rev-list", "--left-right", "--count", "HEAD...origin/main")
      if (counts.ok) {
        const [local, remote] = Str.split(counts.text, /\s+/u)
        if (remote !== undefined && remote !== "0") {
          yield* output.warn(
            `update: diverged from origin/main (${local} local, ${remote} upstream); push or rebase`,
          )
        }
      }
    }
  } else {
    yield* output.warn(`update: fetch failed; keeping local checkout (${fetched.text})`)
  }
  const head = yield* git(home, "rev-parse", "HEAD")
  return head.ok ? head.text : null
})

export const readSyncedCommit = Effect.fn("Update.readSyncedCommit")(function* (stateHome: string) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const content = yield* fs
    .readFileString(path.join(stateHome, SYNCED_STATE_FILE))
    .pipe(Effect.orElseSucceed(() => null))
  if (content === null) {
    return null
  }
  const decoded = yield* Schema.decodeEffect(Schema.fromJsonString(SyncedState))(content).pipe(
    Effect.orElseSucceed(() => null),
  )
  return decoded?.commit ?? null
})

export const recordSyncedCommit = Effect.fn("Update.recordSyncedCommit")(function* (
  stateHome: string,
  commit: string,
) {
  const files = yield* Files
  const path = yield* Path.Path
  const json = yield* Schema.encodeEffect(Schema.fromJsonString(SyncedState))({ commit })
  yield* files.syncTextFile(path.join(stateHome, SYNCED_STATE_FILE), `${json}\n`)
})
