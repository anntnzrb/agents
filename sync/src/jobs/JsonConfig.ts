import { Effect, FileSystem, Record as Rec, Schema, String as Str } from "effect"

import { isObjDict, stripJsonc } from "#domain/Jsonc"
import { Files } from "#platform/Files"

export class JsonConfigError extends Schema.TaggedError<JsonConfigError, { readonly brand: unique symbol }>()(
  "JsonConfigError",
  {
    message: Schema.String,
    cause: Schema.optional(Schema.Defect()),
  },
) {}

const readObject = Effect.fn("JsonConfig.readObject")(function* (path: string, required: boolean) {
  const fs = yield* FileSystem.FileSystem
  const text = yield* fs.readFileString(path).pipe(
    Effect.catchIf(
      (error) => error.reason._tag === "NotFound" && !required,
      () => Effect.succeed(null),
    ),
  )
  if (text === null) {
    return null
  }
  const value = yield* Schema.decodeEffect(Schema.fromJsonString(Schema.Unknown))(stripJsonc(text)).pipe(
    Effect.mapError((cause) => JsonConfigError.make({ message: `parse JSON config ${path}`, cause })),
  )
  if (!isObjDict(value)) {
    return yield* JsonConfigError.make({ message: `expected JSON object: ${path}` })
  }
  return value
})

const missing = Symbol("missing")
function getPath(root: Record<string, unknown>, segments: readonly string[]): unknown {
  let value: unknown = root
  for (const segment of segments) {
    if (!isObjDict(value) || !Rec.has(value, segment)) {
      return missing
    }
    value = value[segment]
  }
  return value
}

function preserve(
  source: Record<string, unknown>,
  previous: Record<string, unknown>,
  preservePaths: readonly string[],
) {
  const result = structuredClone(source)
  let changed = false
  for (const path of preservePaths) {
    const segments = Str.split(".")(path)
    if (getPath(source, segments) !== missing) {
      continue
    }
    const value = getPath(previous, segments)
    if (value === missing) {
      continue
    }
    let node = result
    let blocked = false
    for (const segment of segments.slice(0, -1)) {
      if (!Rec.has(node, segment)) {
        Object.defineProperty(node, segment, {
          value: {},
          writable: true,
          enumerable: true,
          configurable: true,
        })
      }
      const child = node[segment]
      if (!isObjDict(child)) {
        blocked = true
        break
      }
      node = child
    }
    const last = segments.at(-1)
    if (!blocked && last !== undefined) {
      Object.defineProperty(node, last, { value, writable: true, enumerable: true, configurable: true })
      changed = true
    }
  }
  return { result, changed }
}

export const syncJsonConfig = Effect.fn("JsonConfig.syncJsonConfig")(function* (
  src: string,
  dst: string,
  preservePaths: readonly string[] = [],
) {
  const files = yield* Files
  const source = yield* readObject(src, true)
  if (source === null) {
    return yield* JsonConfigError.make({ message: `missing source: ${src}` })
  }
  const previous = (yield* readObject(dst, false)) ?? {}
  const { result, changed } = preserve(source, previous, preservePaths)
  if (changed) {
    const mode = yield* files.existingFileMode(dst)
    const content = yield* Schema.encodeEffect(Schema.fromJsonString(Schema.Unknown, { space: 2 }))(result)
    yield* files.syncTextFile(dst, `${content}\n`, mode)
  } else {
    yield* files.syncManagedTree(src, dst)
  }
})
