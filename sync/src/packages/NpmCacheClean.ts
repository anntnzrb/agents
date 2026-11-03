import { Effect, FileSystem, Option, String as Str } from "effect"

import { joinPath } from "#domain/PathText"
import { Host } from "#platform/Host"
import { Lock } from "#platform/Lock"
import { Proc } from "#platform/Proc"
import { Output } from "#services/Output"

const allocatedBytes = Effect.fn("NpmCacheClean.allocatedBytes")(function* (
  path: string,
): Effect.fn.Return<bigint, never, FileSystem.FileSystem> {
  const fs = yield* FileSystem.FileSystem
  const entries = yield* fs.readDirectory(path).pipe(Effect.orElseSucceed(() => [] as string[]))
  let bytes = 0n
  for (const entry of entries) {
    const child = joinPath(path, entry)
    const info = yield* fs.lstat(child).pipe(Effect.option)
    if (Option.isNone(info)) {
      continue
    }
    if (info.value.type === "Directory") {
      bytes += yield* allocatedBytes(child)
    } else if (Option.isSome(info.value.blocks)) {
      bytes += info.value.blocks.value * 512n
    }
  }
  return bytes
})

const lockPaths = Effect.fn("NpmCacheClean.lockPaths")(function* (root: string) {
  const fs = yield* FileSystem.FileSystem
  const names = yield* fs.readDirectory(root).pipe(Effect.orElseSucceed(() => [] as string[]))
  const paths: string[] = []
  for (const name of names) {
    const path = joinPath(root, name, "lock")
    if (yield* fs.exists(path)) {
      paths.push(path)
    }
  }
  return paths
})

export const cleanNpmCache = Effect.fn("NpmCacheClean.cleanNpmCache")(function* (
  options: { readonly home?: string; readonly cacheHome?: string; readonly dryRun?: boolean } = {},
) {
  const host = yield* Host
  const fs = yield* FileSystem.FileSystem
  const proc = yield* Proc
  const lock = yield* Lock
  const output = yield* Output
  const say = (message: string) => output.write(`npm-cache-clean: ${message}\n`)
  if (!(yield* proc.commandExists("npm"))) {
    yield* say("skip npm: not installed")
    return 0
  }
  const cache = joinPath(options.home ?? host.home, ".npm", "_cacache")
  const info = yield* fs.stat(cache).pipe(Effect.option)
  if (Option.isNone(info) || info.value.type !== "Directory") {
    yield* say("skip npm: cache directory does not exist")
    return 0
  }
  const before = (yield* allocatedBytes(cache)) / 1_048_576n
  const paths = yield* lockPaths(joinPath(options.cacheHome ?? host.cacheHome, "npm-tools"))
  const result = yield* Effect.scoped(
    Effect.gen(function* () {
      const acquired = yield* lock.tryAcquireAll(paths)
      if (Option.isNone(acquired)) {
        yield* say("skip npm: a launcher holds an npm-tools lock")
        return 0
      }
      if (options.dryRun === true) {
        yield* say("would run: npm cache clean --force")
        return 0
      }
      const commandResult = yield* proc.run(["npm", "cache", "clean", "--force"], { timeoutMs: 600_000 })
      if (commandResult.exitCode !== 0) {
        const detail =
          Str.split(
            Str.trim(commandResult.stderr === "" ? commandResult.stdout : commandResult.stderr),
            "\n",
          ).at(-1) ?? ""
        yield* say(`npm cache clean --force exited ${commandResult.exitCode}: ${detail}`)
        yield* say(`npm cache clean --force failed with exit code ${commandResult.exitCode}`)
        return commandResult.exitCode
      }
      const after = (yield* allocatedBytes(cache)) / 1_048_576n
      yield* say(`npm cache ${before}M -> ${after}M`)
      return 0
    }),
  )
  return result
})
