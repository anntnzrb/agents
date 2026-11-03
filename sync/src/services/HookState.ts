import { Effect, FileSystem, Path, Result, Schema } from "effect"
import type { PlatformError } from "effect"

import { fingerprintTree as hashTree, shouldSkipFingerprintEntry } from "#domain/Fingerprint"
import type { FingerprintEntry } from "#domain/Fingerprint"
import { stripJsonc } from "#domain/Jsonc"
import type { ExtensionDepsHookPlan } from "#domain/Plan"
import { HookState, normalizeHookState, prepareHookState } from "#domain/State"
import type { PreparedHookState } from "#domain/State"
import { Files } from "#platform/Files"
import { Output } from "#services/Output"

const generatedNames = ["package.json", "node_modules", "bun.lock", "bun.lockb"] as const
const isMissing = (error: PlatformError.PlatformError): boolean => error.reason._tag === "NotFound"

export class HookStateError extends Schema.TaggedError<HookStateError, { readonly brand: unique symbol }>()(
  "HookStateError",
  { message: Schema.String, path: Schema.String },
) {}

const readFingerprintFile = Effect.fn("HookState.readFingerprintFile")(function* (
  absolute: string,
  name: string,
) {
  const fs = yield* FileSystem.FileSystem
  const content = yield* fs.readFile(absolute).pipe(
    Effect.map((value) => ({ kind: "file" as const, content: value })),
    Effect.catchIf(isMissing, () => Effect.succeed({ kind: "unreadable-file" as const })),
  )
  return { name, ...content }
})

const walkTree = Effect.fn("HookState.walkTree")(function* (
  root: string,
): Effect.fn.Return<
  readonly FingerprintEntry[],
  PlatformError.PlatformError | HookStateError,
  FileSystem.FileSystem | Path.Path
> {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const names = yield* fs
    .readDirectory(root)
    .pipe(Effect.catchIf(isMissing, () => Effect.succeed([] as string[])))
  const entries: FingerprintEntry[] = []
  for (const name of names) {
    if (shouldSkipFingerprintEntry(name)) {
      continue
    }
    const absolute = path.join(root, name)
    const info = yield* fs.lstat(absolute).pipe(
      Effect.map((value) => value.type),
      Effect.catchIf(isMissing, () => Effect.succeed("Missing" as const)),
    )
    if (info === "Directory") {
      entries.push({ name, kind: "directory", entries: yield* walkTree(absolute) })
    } else if (info === "SymbolicLink") {
      const target = yield* fs.stat(absolute).pipe(
        Effect.map((value) => value.type),
        Effect.catchIf(isMissing, () => Effect.succeed("Missing" as const)),
      )
      if (target === "Missing") {
        entries.push({ name, kind: "broken" })
        continue
      }
      if (target === "Directory") {
        return yield* HookStateError.make({
          path: absolute,
          message: `refusing source directory symlink: ${absolute}`,
        })
      }
      const entry = yield* readFingerprintFile(absolute, name)
      entries.push(entry)
    } else if (info === "File") {
      const entry = yield* readFingerprintFile(absolute, name)
      entries.push(entry)
    }
  }
  return entries
})

export const fingerprintTree = Effect.fn("HookState.fingerprintTree")(function* (root: string) {
  const fs = yield* FileSystem.FileSystem
  const exists = yield* fs.lstat(root).pipe(
    Effect.as(true),
    Effect.orElseSucceed(() => false),
  )
  return hashTree(exists ? yield* walkTree(root) : null)
})

export const loadExtensionHookState = Effect.fn("HookState.loadExtensionHookState")(function* (path: string) {
  const fs = yield* FileSystem.FileSystem
  const output = yield* Output
  const bytes = yield* fs.readFile(path).pipe(
    Effect.map((value) => ({ value, error: null })),
    Effect.catch((error) => Effect.succeed({ value: null, error })),
  )
  if (bytes.value === null) {
    if (bytes.error !== null && !isMissing(bytes.error)) {
      yield* output.warn(`hook state read failed, ignoring ${path} (${bytes.error.message})`)
    }
    return null
  }
  const bytesValue = bytes.value
  const content = yield* Effect.try({
    try: () => new TextDecoder("utf-8", { fatal: true }).decode(bytesValue),
    catch: () => HookStateError.make({ path, message: "invalid UTF-8" }),
  }).pipe(Effect.orElseSucceed(() => null))
  if (content === null) {
    yield* output.warn(`hook state read failed, ignoring ${path} (invalid UTF-8)`)
    return null
  }
  const decoded = Schema.decodeResult(Schema.fromJsonString(HookState))(stripJsonc(content))
  if (Result.isFailure(decoded)) {
    yield* output.warn(`hook state parse failed, ignoring ${path} (invalid shape)`)
    return null
  }
  return normalizeHookState(decoded.success)
})

const existsEntry = Effect.fn("HookState.existsEntry")(function* (path: string) {
  const fs = yield* FileSystem.FileSystem
  return yield* fs.lstat(path).pipe(
    Effect.as(true),
    Effect.orElseSucceed(() => false),
  )
})

export const prepareExtensionHookState = Effect.fn("HookState.prepareExtensionHookState")(function* (
  hook: ExtensionDepsHookPlan,
  fingerprint?: string,
) {
  const path = yield* Path.Path
  const current = fingerprint ?? (yield* fingerprintTree(hook.sourceRoot))
  const previous = yield* loadExtensionHookState(hook.statePath)
  const existing = new Set<string>()
  if (previous !== null && previous.fingerprint === current) {
    for (const entry of previous.generatedEntries) {
      if (yield* existsEntry(path.resolve(hook.root, entry))) {
        existing.add(entry)
      }
    }
  }
  return prepareHookState(current, previous, hook.relativeRoot, (entry) => existing.has(entry))
})

export const findGeneratedExtensionEntries = Effect.fn("HookState.findGeneratedExtensionEntries")(function* (
  root: string,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const results: string[] = []
  for (const name of generatedNames) {
    if (yield* existsEntry(path.join(root, name))) {
      results.push(name)
    }
  }
  const children = yield* fs.readDirectory(root).pipe(Effect.orElseSucceed(() => [] as string[]))
  for (const child of children) {
    if (shouldSkipFingerprintEntry(child)) {
      continue
    }
    const directory = yield* fs.lstat(path.join(root, child)).pipe(
      Effect.map((info) => info.type === "Directory"),
      Effect.orElseSucceed(() => false),
    )
    if (!directory) {
      continue
    }
    for (const name of generatedNames) {
      if (yield* existsEntry(path.join(root, child, name))) {
        results.push(`${child}/${name}`)
      }
    }
  }
  return [...new Set(results)]
})

export const recordExtensionHookState = Effect.fn("HookState.recordExtensionHookState")(function* (
  hook: ExtensionDepsHookPlan,
  prepared: PreparedHookState,
) {
  const files = yield* Files
  const generatedEntries = yield* findGeneratedExtensionEntries(hook.root)
  const mode = yield* files.existingFileMode(hook.statePath)
  const payload = yield* Schema.encodeEffect(Schema.fromJsonString(HookState, { space: 2 }))({
    fingerprint: prepared.fingerprint,
    generatedEntries,
  })
  yield* files.syncTextFile(hook.statePath, `${payload}\n`, mode)
})

export const clearExtensionHookState = Effect.fn("HookState.clearExtensionHookState")(function* (
  path: string,
) {
  const fs = yield* FileSystem.FileSystem
  yield* fs.remove(path).pipe(Effect.ignore)
})
