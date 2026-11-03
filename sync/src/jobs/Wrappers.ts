import { Array as Arr, Effect, FileSystem, Path, Schema, String as Str } from "effect"

import type { Harness, SyncEnvPaths } from "#domain/Harness"
import { stripJsonc } from "#domain/Jsonc"
import { joinPath } from "#domain/PathText"
import { normalizeWrapperState, uniqueSorted, WrapperState } from "#domain/State"
import { TOOL_LAUNCHERS } from "#domain/ToolLaunchers"
import { Files } from "#platform/Files"
import { Output } from "#services/Output"

export const WRAPPER_MARKER = "agents-managed-wrapper:v1"
export const WRAPPER_STATE_FILE = "wrappers.json"
export const WRAPPER_FILE_MODE = 0o755

export interface WrapperDestination {
  readonly path: string
  readonly content: string
}
export interface WrapperReconcileResult {
  readonly owned: readonly string[]
  readonly conflicts: readonly string[]
  readonly removed: readonly string[]
}
export type WrapperEnv = Pick<SyncEnvPaths, "home" | "runtimeHome" | "managedStateHome"> & {
  readonly harnesses: readonly Harness[]
}

export const shellQuote = (value: string): string => `'${Str.replaceAll("'", `'"'"'`)(value)}'`
export const wrapperDirectory = (env: Pick<SyncEnvPaths, "home">): string =>
  joinPath(env.home, ".local", "bin")

export const renderLaunchWrapper = (runtimeHome: string, sourceName: string): string => {
  const executable = shellQuote(joinPath(runtimeHome, "sync-current", "sync"))
  return Arr.join(
    [
      "#!/bin/sh",
      `# ${WRAPPER_MARKER}`,
      "set -eu",
      `if [ ! -x ${executable} ]; then`,
      "  echo 'agents: sync runtime is missing; run sync from the agents repository' >&2",
      "  exit 127",
      "fi",
      `exec ${executable} launch ${shellQuote(sourceName)} -- "$@"`,
      "",
    ],
    "\n",
  )
}

export const renderManagedToolWrapper = (executable: string, args: readonly string[] = []): string =>
  Arr.join(
    [
      "#!/bin/sh",
      `# ${WRAPPER_MARKER}`,
      "set -eu",
      `exec ${Arr.join(Arr.map((arg: string) => shellQuote(arg))([executable, ...args]), " ")} "$@"`,
      "",
    ],
    "\n",
  )

export const wrapperDestinations = (env: WrapperEnv): WrapperDestination[] => [
  ...Arr.map((harness: Harness) => ({
    path: joinPath(wrapperDirectory(env), harness.launcher.bin),
    content: renderLaunchWrapper(env.runtimeHome, harness.sourceName),
  }))(env.harnesses),
  ...Arr.map((tool: (typeof TOOL_LAUNCHERS)[number]) => ({
    path: joinPath(wrapperDirectory(env), tool.bin),
    content: renderLaunchWrapper(env.runtimeHome, tool.id),
  }))(TOOL_LAUNCHERS),
]

const emptyState = (): WrapperState => ({ version: 1, entries: [] })
const stateJson = Schema.fromJsonString(WrapperState)
const decodeState = Schema.decodeEffect(stateJson)
const encodeState = Schema.encodeEffect(Schema.fromJsonString(WrapperState, { space: 2 }))
const utf8 = new TextDecoder("utf-8", { fatal: true })

export const readWrapperState = Effect.fn("Wrappers.readWrapperState")(function* (statePath: string) {
  const fs = yield* FileSystem.FileSystem
  const output = yield* Output
  const bytes = yield* fs.readFile(statePath).pipe(
    Effect.map((data) => data as Uint8Array | null),
    Effect.catchIf(
      (error) => error.reason._tag === "NotFound",
      () => Effect.succeed(null),
    ),
  )
  if (bytes === null) {
    return emptyState()
  }
  const parsed = yield* Effect.try({
    try: () => stripJsonc(utf8.decode(bytes)),
    catch: () => "invalid utf8" as const,
  }).pipe(
    Effect.flatMap(decodeState),
    Effect.map(normalizeWrapperState),
    Effect.catch(() =>
      Effect.gen(function* () {
        yield* output.warn(`wrapper state parse failed, ignoring ${statePath} (invalid shape)`)
        return emptyState()
      }),
    ),
  )
  return parsed
})

export const writeWrapperState = Effect.fn("Wrappers.writeWrapperState")(function* (
  statePath: string,
  state: WrapperState,
) {
  const files = yield* Files
  const mode = yield* files.existingFileMode(statePath)
  const content = yield* encodeState(state)
  yield* files.syncTextFile(statePath, `${content}\n`, mode)
})

export const isManagedWrapper = Effect.fn("Wrappers.isManagedWrapper")(function* (target: string) {
  const fs = yield* FileSystem.FileSystem
  const info = yield* fs.lstat(target).pipe(Effect.orElseSucceed(() => null))
  if (info === null || info.type !== "File") {
    return false
  }
  return yield* fs.readFile(target).pipe(
    Effect.flatMap((bytes) =>
      Effect.try({
        try: () => Str.includes(WRAPPER_MARKER)(utf8.decode(bytes)),
        catch: () => "invalid utf8" as const,
      }),
    ),
    Effect.orElseSucceed(() => false),
  )
})

export const writeManagedWrapper = Effect.fn("Wrappers.writeManagedWrapper")(function* (
  target: string,
  content: string,
) {
  const fs = yield* FileSystem.FileSystem
  const files = yield* Files
  const info = yield* fs.lstat(target).pipe(
    Effect.map((value) => value as FileSystem.File.Info | null),
    Effect.catchIf(
      (error) => error.reason._tag === "NotFound",
      () => Effect.succeed(null),
    ),
  )
  if (info !== null) {
    if (info.type !== "File" || !(yield* isManagedWrapper(target))) {
      return "conflict" as const
    }
    const existing = yield* fs.readFile(target)
    const text = yield* Effect.try({
      try: () => utf8.decode(existing),
      catch: () => "invalid utf8" as const,
    }).pipe(Effect.orElseSucceed(() => null))
    if (text === null) {
      return "conflict" as const
    }
    if (text === content) {
      if ((info.mode & 0o777) !== WRAPPER_FILE_MODE) {
        yield* fs.chmod(target, WRAPPER_FILE_MODE)
      }
      return "owned" as const
    }
  }
  yield* files.syncTextFile(target, content, WRAPPER_FILE_MODE)
  return "owned" as const
})

// Resolve existing ancestors as well as the final directory, matching realpath's
// behavior for paths whose final components have not been created yet.
const canonicalDirectory = Effect.fn("Wrappers.canonicalDirectory")(function* (directory: string) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  let current = path.resolve(directory)
  const suffix: string[] = []
  while (true) {
    const resolved = yield* fs.realPath(current).pipe(
      Effect.map((value) => value as string | null),
      Effect.catchIf(
        (error) => error.reason._tag === "NotFound",
        () => Effect.succeed(null),
      ),
    )
    if (resolved !== null) {
      return path.resolve(resolved, ...suffix)
    }
    const parent = path.dirname(current)
    if (parent === current) {
      return path.resolve(current, ...suffix)
    }
    suffix.unshift(path.basename(current))
    current = parent
  }
})

export const reconcileWrapperFiles = Effect.fn("Wrappers.reconcileWrapperFiles")(function* (
  env: Pick<WrapperEnv, "home" | "managedStateHome">,
  desired: readonly WrapperDestination[],
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const statePath = path.join(env.managedStateHome, WRAPPER_STATE_FILE)
  const previous = yield* readWrapperState(statePath)
  const desiredPaths = new Set(Arr.map((entry: WrapperDestination) => entry.path)(desired))
  const allowed = new Set<string>()
  for (const dir of [
    wrapperDirectory(env),
    ...Arr.map((entry: WrapperDestination) => path.dirname(entry.path))(desired),
  ]) {
    const canonical = yield* canonicalDirectory(dir)
    allowed.add(canonical)
  }
  const owned: string[] = []
  const conflicts: string[] = []
  const removed: string[] = []
  for (const oldPath of previous.entries) {
    if (desiredPaths.has(oldPath)) {
      continue
    }
    const canonical = yield* canonicalDirectory(path.dirname(oldPath))
    if (!allowed.has(canonical) || !(yield* isManagedWrapper(oldPath))) {
      conflicts.push(oldPath)
    } else {
      yield* fs.remove(oldPath, { force: true })
      removed.push(oldPath)
    }
  }
  for (const entry of desired) {
    if ((yield* writeManagedWrapper(entry.path, entry.content)) === "owned") {
      owned.push(entry.path)
    } else {
      conflicts.push(entry.path)
    }
  }
  yield* writeWrapperState(statePath, { version: 1, entries: uniqueSorted(owned) })
  return { owned, conflicts: uniqueSorted(conflicts), removed } satisfies WrapperReconcileResult
})

export const reconcileWrappers = Effect.fn("Wrappers.reconcileWrappers")(function* (env: WrapperEnv) {
  const output = yield* Output
  const result = yield* reconcileWrapperFiles(env, wrapperDestinations(env))
  for (const conflict of result.conflicts) {
    yield* output.warn(`preserving unmanaged wrapper conflict: ${conflict}`)
  }
  return result
})
