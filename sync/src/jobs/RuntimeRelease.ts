import { Array as Arr, Effect, FileSystem, Option, Path, Record as Rec, Schema, String as Str } from "effect"
import type { PlatformError } from "effect"

import { IGNORED_SYNC_NAMES } from "#domain/EntryNames"
import { compareCodePoints } from "#domain/Fingerprint"
import type { SyncRuntimeInstallJob } from "#domain/Plan"
import { Host } from "#platform/Host"
import { Links } from "#platform/Links"
import { Proc } from "#platform/Proc"
import { Output } from "#services/Output"

export class RuntimeReleaseError extends Schema.TaggedError<
  RuntimeReleaseError,
  { readonly brand: unique symbol }
>()("RuntimeReleaseError", { message: Schema.String }) {}

const hashTree = Effect.fn("RuntimeRelease.hashTree")(function* (
  root: string,
  hash: Bun.CryptoHasher,
  prefix = "",
): Effect.fn.Return<
  void,
  PlatformError.PlatformError | RuntimeReleaseError,
  FileSystem.FileSystem | Path.Path
> {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const names = yield* fs.readDirectory(root)
  for (const name of Arr.sort(names, compareCodePoints)) {
    if (Rec.has(IGNORED_SYNC_NAMES, name)) {
      continue
    }
    const relative = prefix === "" ? name : `${prefix}/${name}`
    const full = path.join(root, name)
    const info = yield* fs.lstat(full)
    if (info.type === "SymbolicLink") {
      const target = yield* fs.stat(full)
      if (target.type !== "File") {
        return yield* RuntimeReleaseError.make({ message: `refusing source directory symlink: ${full}` })
      }
    } else if (info.type === "Directory") {
      hash.update(`dir:${relative}\n`)
      yield* hashTree(full, hash, relative)
      continue
    } else if (info.type !== "File") {
      continue
    }
    hash.update(`file:${relative}\n`)
    const content = yield* fs.readFile(full)
    hash.update(content)
    hash.update("\n")
  }
})

const copyTree = Effect.fn("RuntimeRelease.copyTree")(function* (
  source: string,
  destination: string,
): Effect.fn.Return<void, PlatformError.PlatformError, FileSystem.FileSystem | Path.Path> {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  yield* fs.makeDirectory(destination, { recursive: true })
  for (const name of yield* fs.readDirectory(source)) {
    if (Rec.has(IGNORED_SYNC_NAMES, name)) {
      continue
    }
    const from = path.join(source, name)
    const to = path.join(destination, name)
    const info = yield* fs.lstat(from)
    if (info.type === "Directory") {
      yield* copyTree(from, to)
    } else if (info.type === "File" || info.type === "SymbolicLink") {
      yield* fs.copyFile(from, to)
    }
  }
})

const complete = Effect.fn("RuntimeRelease.complete")(function* (directory: string) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const marker = path.join(directory, ".release-complete")
  const binary = path.join(directory, "sync")
  if (!(yield* fs.exists(marker)) || !(yield* fs.exists(binary))) {
    return false
  }
  return (yield* fs.stat(binary)).type === "File"
})

const publish = Effect.fn("RuntimeRelease.publish")(function* (current: string, release: string) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const links = yield* Links
  yield* fs.makeDirectory(path.dirname(current), { recursive: true })
  yield* links.replaceLink(current, path.relative(path.dirname(current), release))
})

const runChecked = Effect.fn("RuntimeRelease.runChecked")(function* (
  command: readonly string[],
  cwd: string,
  timeoutMs: number,
  label: string,
) {
  const proc = yield* Proc
  const result = yield* proc.run(command, { cwd, timeoutMs })
  if (result.timedOut || result.outputLimited || result.exitCode !== 0) {
    const detail = result.timedOut
      ? "timed out"
      : result.outputLimited
        ? "output limit exceeded"
        : Str.trim(result.stderr || result.stdout || "unknown error")
    return yield* RuntimeReleaseError.make({ message: `${label}: ${detail}` })
  }
})

const releaseId = Effect.fn("RuntimeRelease.releaseId")(function* (job: SyncRuntimeInstallJob) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const src = path.join(job.sourceRoot, "src")
  for (const [name, kind] of [
    ["src", "Directory"],
    ["package.json", "File"],
    ["bun.lock", "File"],
  ] as const) {
    const source = path.join(job.sourceRoot, name)
    const info = yield* fs.lstat(source)
    if (info.type !== kind) {
      return yield* RuntimeReleaseError.make({ message: `invalid runtime source ${source}` })
    }
    yield* fs.access(source, { readable: true })
  }
  const hash = new Bun.CryptoHasher("sha256")
  yield* hashTree(src, hash)
  const manifest = yield* fs.readFile(path.join(job.sourceRoot, "package.json"))
  const lock = yield* fs.readFile(path.join(job.sourceRoot, "bun.lock"))
  hash.update(manifest)
  hash.update(lock)
  return hash.digest("hex")
})

const compileStage = Effect.fn("RuntimeRelease.compileStage")(function* (stage: string, timeoutMs: number) {
  const path = yield* Path.Path
  yield* runChecked(
    ["bun", "install", "--frozen-lockfile", "--production"],
    stage,
    timeoutMs,
    "runtime dependency install failed",
  )
  yield* runChecked(
    ["bun", "build", "--compile", path.join(stage, "src", "main.ts"), "--outfile", path.join(stage, "sync")],
    stage,
    timeoutMs,
    "runtime build failed",
  )
  yield* runChecked([path.join(stage, "sync"), "--help"], stage, timeoutMs, "runtime smoke check failed")
})

const buildRelease = Effect.fn("RuntimeRelease.buildRelease")(function* (
  job: SyncRuntimeInstallJob,
  id: string,
  release: string,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const host = yield* Host
  const src = path.join(job.sourceRoot, "src")
  yield* Effect.scoped(
    Effect.gen(function* () {
      const temporary = yield* fs.makeTempDirectoryScoped({
        directory: job.releasesRoot,
        prefix: `.stage-${host.pid}-`,
      })
      const suffix = Arr.map([...new TextEncoder().encode(path.basename(temporary))], (byte: number) =>
        byte.toString(16),
      )
      const stage = path.join(job.releasesRoot, `.stage-${host.pid}-${Arr.join(suffix, "")}`)
      yield* Effect.acquireRelease(fs.rename(temporary, stage), () =>
        fs.remove(stage, { recursive: true, force: true }).pipe(Effect.ignore),
      )
      yield* copyTree(src, path.join(stage, "src"))
      yield* fs.copyFile(path.join(job.sourceRoot, "package.json"), path.join(stage, "package.json"))
      yield* fs.copyFile(path.join(job.sourceRoot, "bun.lock"), path.join(stage, "bun.lock"))
      yield* compileStage(stage, job.timeoutMs)
      yield* fs.writeFileString(path.join(stage, ".release-complete"), `${id}\n`)
      if (!(yield* complete(stage))) {
        return yield* RuntimeReleaseError.make({
          message: "runtime install did not produce a complete release",
        })
      }
      if (yield* fs.exists(release)) {
        if (yield* complete(release)) {
          return
        }
        yield* fs.remove(release, { recursive: true, force: true })
      }
      yield* fs.rename(stage, release)
    }),
  )
})

export const installRuntimeRelease = Effect.fn("RuntimeRelease.install")(function* (
  job: SyncRuntimeInstallJob,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const id = yield* releaseId(job)
  const release = path.join(job.releasesRoot, id)
  yield* fs.makeDirectory(job.releasesRoot, { recursive: true })
  if (!(yield* complete(release))) {
    yield* buildRelease(job, id, release)
  }
  yield* publish(job.currentLink, release)
})

const pruneEntries = Effect.fn("RuntimeRelease.pruneEntries")(function* (
  releasesRoot: string,
  current: string,
  timeoutMs: number,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const host = yield* Host
  const output = yield* Output
  const now = yield* host.now
  const listed = yield* Effect.result(fs.readDirectory(releasesRoot))
  if (listed._tag === "Failure") {
    yield* output.warn(`failed to list releases for pruning: ${String(listed.failure)}`)
    return
  }
  for (const name of listed.success) {
    const entry = path.join(releasesRoot, name)
    const info = yield* fs.lstat(entry)
    if (info.type !== "Directory") {
      continue
    }
    const stage = /^\.stage-(\d+)-([a-f0-9]+)$/iu.exec(name)
    if (stage !== null) {
      const dead = !(yield* host.isPidAlive(Number(stage[1] ?? "0")))
      const stale = Option.isSome(info.mtime) && now - info.mtime.value.getTime() > timeoutMs
      if (dead || stale) {
        yield* fs
          .remove(entry, { recursive: true, force: true })
          .pipe(
            Effect.catch((error) =>
              output.warn(`failed to prune stale stage directory ${name}: ${String(error)}`),
            ),
          )
      }
      continue
    }
    if (name !== current && /^[a-f0-9]{64}$/iu.test(name) && (yield* complete(entry))) {
      yield* fs
        .remove(entry, { recursive: true, force: true })
        .pipe(
          Effect.catch((error) =>
            output.warn(`failed to prune unreferenced release ${name}: ${String(error)}`),
          ),
        )
    }
  }
})

export const pruneUnreferencedReleases = Effect.fn("RuntimeRelease.prune")(function* (
  releasesRoot: string,
  currentLink: string,
  timeoutMs: number,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const output = yield* Output
  if (!(yield* fs.exists(releasesRoot)) || !(yield* fs.exists(currentLink))) {
    return
  }
  const resolved = yield* Effect.result(fs.realPath(currentLink))
  if (resolved._tag === "Failure") {
    yield* output.warn(`failed to resolve current release link for pruning: ${String(resolved.failure)}`)
    return
  }
  const current = path.basename(resolved.success)
  if (/^[a-f0-9]{64}$/iu.test(current)) {
    yield* pruneEntries(releasesRoot, current, timeoutMs)
  }
})
