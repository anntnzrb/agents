import { Array as Arr, Effect, FileSystem, Option, Schema, String as Str } from "effect"

import { isSafeManagedEntryName } from "#domain/EntryNames"
import { harnessFromAdapter, harnessManagedStatePath, harnessRoot } from "#domain/Harness"
import { HARNESS_ADAPTERS } from "#domain/HarnessAdapters"
import type { HostPlatform } from "#domain/HarnessAdapters"
import { joinPath } from "#domain/PathText"
import type { SyncPlan } from "#domain/Plan"
import { ManagedEntries, normalizeManagedEntries, uniqueSorted } from "#domain/State"
import { Files } from "#platform/Files"
import { Output } from "#services/Output"

export interface ManagedHarnessPlan {
  readonly statePath: string
  readonly cleanupPaths: readonly string[]
  readonly currentEntryNames: readonly string[]
  readonly active: boolean
}

export interface ManagedSyncPlan {
  readonly harnesses: readonly ManagedHarnessPlan[]
}

export interface ManagedStateEnv {
  readonly home: string
  readonly managedStateHome: string
  readonly platform: HostPlatform
}

const decodeEntries = Schema.decodeEffect(Schema.fromJsonString(ManagedEntries))
const encodeEntries = Schema.encodeEffect(Schema.fromJsonString(ManagedEntries, { space: 2 }))
const errorMessage = (error: unknown): string => (error instanceof Error ? error.message : String(error))
const asciiJson = (json: string): string => {
  let result = ""
  for (const character of json) {
    const code = Option.getOrElse(Str.codePointAt(0)(character), () => 0)
    if (code < 127) {
      result += character
    } else if (code <= 65_535) {
      result += `\\u${Str.padStart(4, "0")(code.toString(16))}`
    } else {
      const value = code - 65_536
      result += `\\u${(55_296 + (value >> 10)).toString(16)}\\u${(56_320 + (value & 1023)).toString(16)}`
    }
  }
  return result
}

class SchemaError extends Schema.TaggedError<SchemaError, { readonly brand: unique symbol }>()(
  "ManagedStateDecodeError",
  { cause: Schema.Defect() },
) {}

export const loadRecordedEntryNames = Effect.fn("ManagedState.loadRecordedEntryNames")(function* (
  path: string,
) {
  const fs = yield* FileSystem.FileSystem
  const output = yield* Output
  const read = fs.readFile(path).pipe(
    Effect.flatMap((bytes) =>
      Effect.try({
        try: () => new TextDecoder("utf-8", { fatal: true }).decode(bytes),
        catch: (error) => SchemaError.make({ cause: error }),
      }),
    ),
    Effect.flatMap(decodeEntries),
    Effect.map(normalizeManagedEntries),
    Effect.catch((error) => {
      if (error._tag === "PlatformError" && error.reason._tag === "NotFound") {
        return Effect.succeed([])
      }
      return output
        .warn(`ignoring malformed managed state ${path} (${errorMessage(error)})`)
        .pipe(Effect.as([] as string[]))
    }),
  )
  return yield* read
})

export const writeRecordedEntryNames = Effect.fn("ManagedState.writeRecordedEntryNames")(function* (
  path: string,
  entryNames: readonly string[],
) {
  const files = yield* Files
  const mode = yield* files.existingFileMode(path)
  const encoded = yield* encodeEntries(uniqueSorted(entryNames))
  const json = asciiJson(encoded)
  yield* files.syncTextFile(path, `${json}\n`, mode)
})
export const planManagedEntriesForSyncPlan = Effect.fn("ManagedState.planManagedEntriesForSyncPlan")(
  function* (env: ManagedStateEnv, syncPlan: Pick<SyncPlan, "harnesses">) {
    const fs = yield* FileSystem.FileSystem
    const output = yield* Output
    const activeIds = new Set(
      Arr.map((plan: SyncPlan["harnesses"][number]) => plan.harness.id)(syncPlan.harnesses),
    )
    const harnesses: ManagedHarnessPlan[] = []
    for (const plan of syncPlan.harnesses) {
      const current = new Set(plan.currentEntryNames)
      const recorded = yield* loadRecordedEntryNames(plan.statePath)
      const stale = Arr.filter(
        uniqueSorted([...plan.cleanupEntryNames, ...recorded]),
        (name) => !current.has(name),
      )
      const cleanupPaths: string[] = []
      for (const name of stale) {
        if (isSafeManagedEntryName(name)) {
          cleanupPaths.push(joinPath(plan.root, name))
        } else {
          yield* output.warn(`skipping unsafe recorded managed entry name: ${name}`)
        }
      }
      harnesses.push({
        statePath: plan.statePath,
        cleanupPaths,
        currentEntryNames: [...plan.currentEntryNames],
        active: true,
      })
    }
    for (const adapter of HARNESS_ADAPTERS) {
      if (!adapter.platforms.includes(env.platform) || activeIds.has(adapter.id)) {
        continue
      }
      const harness = harnessFromAdapter(adapter, env.home)
      const statePath = harnessManagedStatePath(harness, env.managedStateHome)
      if (!(yield* fs.exists(statePath))) {
        continue
      }
      const recorded = yield* loadRecordedEntryNames(statePath)
      harnesses.push({
        statePath,
        cleanupPaths: Arr.map((name: string) => joinPath(harnessRoot(harness), name))(recorded),
        currentEntryNames: [],
        active: false,
      })
    }
    return { harnesses } satisfies ManagedSyncPlan
  },
)

export const cleanManagedEntries = Effect.fn("ManagedState.cleanManagedEntries")(function* (
  plan: ManagedSyncPlan,
) {
  const files = yield* Files
  const output = yield* Output
  let success = true
  for (const harness of plan.harnesses) {
    for (const path of harness.cleanupPaths) {
      const cleaned = yield* files.rmEntry(path).pipe(
        Effect.as(true),
        Effect.catch((error) =>
          output.err(`cleanup failed: ${path} (${errorMessage(error.cause)})`).pipe(Effect.as(false)),
        ),
      )
      success = cleaned && success
    }
  }
  return success
})

export const recordManagedEntries = Effect.fn("ManagedState.recordManagedEntries")(function* (
  plan: ManagedSyncPlan,
) {
  const fs = yield* FileSystem.FileSystem
  const output = yield* Output
  let success = true
  for (const harness of plan.harnesses) {
    const recorded = yield* harness.active
      ? writeRecordedEntryNames(harness.statePath, harness.currentEntryNames).pipe(
          Effect.as(true),
          Effect.catch((error) =>
            output.err(`managed state write failed: ${errorMessage(error.cause)}`).pipe(Effect.as(false)),
          ),
        )
      : fs.remove(harness.statePath, { force: true }).pipe(
          Effect.as(true),
          Effect.catch((error) =>
            output
              .err(`managed state removal failed: ${harness.statePath} (${errorMessage(error)})`)
              .pipe(Effect.as(false)),
          ),
        )
    success = recorded && success
  }
  return success
})
