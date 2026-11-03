import { randomUUID } from "node:crypto"
import { lstatSync, readlinkSync, renameSync, symlinkSync, unlinkSync } from "node:fs"

import { Context, Effect, Layer, Option, Schema } from "effect"

export class LinksError extends Schema.TaggedError<LinksError, { readonly brand: unique symbol }>()(
  "LinksError",
  {
    path: Schema.String,
    operation: Schema.String,
    cause: Schema.Defect(),
  },
) {}

export class Links extends Context.Service<
  Links,
  {
    readonly readLinkTarget: (path: string) => Effect.Effect<Option.Option<string>, LinksError>
    readonly replaceLink: (path: string, target: string) => Effect.Effect<void, LinksError>
  }
>()("agents-sync/platform/Links") {}

const isMissing = (error: unknown): boolean =>
  error instanceof Error && "code" in error && error.code === "ENOENT"

const unlinkIfPresent = (path: string): void => {
  try {
    unlinkSync(path)
  } catch (error) {
    if (!isMissing(error)) {
      throw error
    }
  }
}

const readLinkTarget = Effect.fn("Links.readLinkTarget")(function* (path: string) {
  return yield* Effect.try({
    try: () => {
      try {
        const stat = lstatSync(path)
        if (!stat.isSymbolicLink()) {
          throw new Error(`cache entry is not a symlink: ${path}`)
        }
        return Option.some(readlinkSync(path))
      } catch (error) {
        if (isMissing(error)) {
          return Option.none<string>()
        }
        throw error
      }
    },
    catch: (cause) => LinksError.make({ path, operation: "read link", cause }),
  })
})

const replaceLink = Effect.fn("Links.replaceLink")(function* (path: string, target: string) {
  yield* Effect.try({
    try: () => {
      const temp = `${path}.${randomUUID()}.tmp`
      symlinkSync(target, temp)
      try {
        try {
          if (!lstatSync(path).isSymbolicLink()) {
            throw new Error(`unmanaged conflict at ${path}`)
          }
        } catch (error) {
          if (!isMissing(error)) {
            throw error
          }
        }
        renameSync(temp, path)
      } finally {
        unlinkIfPresent(temp)
      }
    },
    catch: (cause) => LinksError.make({ path, operation: "replace link", cause }),
  })
})

export const LinksPosix = Layer.succeed(Links, Links.of({ readLinkTarget, replaceLink }))
