import {
  chmodSync,
  constants,
  closeSync,
  copyFileSync,
  fchmodSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  unlinkSync,
  utimesSync,
  writeSync,
} from "node:fs"
import type { Stats } from "node:fs"
import nodePath from "node:path"

import { Array as Arr, Context, Effect, Layer, Schema, String as Str } from "effect"

import { isIgnoredSyncEntry } from "#domain/EntryNames"

const { basename, dirname, join } = nodePath
const filter = Arr.filter

export const OUTPUT_MODE = 0o600
export interface CachedSourceContent {
  readonly metadata: Stats
  readonly content: Uint8Array
}
export type SourceContentCache = Map<string, CachedSourceContent>

export class FilesError extends Schema.TaggedError<FilesError, { readonly brand: unique symbol }>()(
  "FilesError",
  {
    operation: Schema.String,
    path: Schema.String,
    cause: Schema.Defect(),
  },
) {}

export class Files extends Context.Service<
  Files,
  {
    readonly isSymlink: (path: string) => Effect.Effect<boolean, FilesError>
    readonly rmEntry: (path: string) => Effect.Effect<void, FilesError>
    readonly isIdenticalFile: (
      src: string,
      metadata: Stats,
      dst: string,
      cache?: SourceContentCache,
    ) => Effect.Effect<boolean, FilesError>
    readonly syncManagedTree: (
      src: string,
      dst: string,
      preservePaths?: readonly string[],
      cache?: SourceContentCache,
    ) => Effect.Effect<void, FilesError>
    readonly syncManagedChildren: (
      src: string,
      dst: string,
      preservePaths?: readonly string[],
      cache?: SourceContentCache,
    ) => Effect.Effect<void, FilesError>
    readonly existingFileMode: (path: string) => Effect.Effect<number, FilesError>
    readonly syncTextFile: (path: string, content: string, mode?: number) => Effect.Effect<void, FilesError>
    readonly isExecutable: (path: string) => Effect.Effect<boolean, FilesError>
  }
>()("agents-sync/platform/Files") {}

const missing = (error: unknown): boolean =>
  typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT"

const remove = (path: string): void => {
  try {
    rmSync(path, { recursive: true, force: true })
  } catch (error) {
    if (!missing(error)) {
      throw error
    }
  }
}

const sourceMetadata = (path: string): Stats => {
  const metadata = lstatSync(path)
  if (!metadata.isSymbolicLink()) {
    return metadata
  }
  const target = statSync(path)
  if (target.isDirectory()) {
    throw new Error(`refusing source directory symlink: ${path}`)
  }
  return target
}

const identical = (src: string, metadata: Stats, dst: string, cache?: SourceContentCache): boolean => {
  if (metadata.isDirectory()) {
    return false
  }
  let target: Stats
  try {
    target = lstatSync(dst)
  } catch {
    return false
  }
  if (
    !target.isFile() ||
    metadata.size !== target.size ||
    (metadata.mode & 0o777) !== (target.mode & 0o777)
  ) {
    return false
  }
  if (metadata.size === 0) {
    return true
  }
  // Every copy stamps the source mtime onto the destination (utimes keeps milliseconds), so a
  // matching size, mode, and millisecond mtime means this destination is that copy, as in rsync's
  // quick check. A changed source or a destination edited in place moves its mtime and is compared.
  if (Math.trunc(metadata.mtimeMs) === Math.trunc(target.mtimeMs)) {
    return true
  }
  const cached = cache?.get(src)
  const old = cached?.metadata
  const content =
    cached !== undefined &&
    old !== undefined &&
    old.size === metadata.size &&
    old.mode === metadata.mode &&
    old.mtimeMs === metadata.mtimeMs &&
    old.ctimeMs === metadata.ctimeMs
      ? cached.content
      : readFileSync(src)
  if (content !== cached?.content) {
    cache?.set(src, { metadata, content })
  }
  return Buffer.from(content).equals(readFileSync(dst))
}

const childPreserve = (paths: readonly string[], name: string): string[] => {
  const prefix = `${name}/`
  return Arr.map((item: string) => Str.slice(prefix.length)(item))(
    filter(paths, (item) => Str.startsWith(prefix)(item)),
  )
}
const entries = (path: string): string[] => {
  try {
    return readdirSync(path)
  } catch (error) {
    if (missing(error)) {
      return []
    }
    throw error
  }
}
const prune = (dst: string, paths: readonly string[]): void => {
  for (const name of entries(dst)) {
    if (paths.includes(name)) {
      continue
    }
    const child = join(dst, name)
    const nested = childPreserve(paths, name)
    if (nested.length > 0 && lstatSync(child).isDirectory()) {
      prune(child, nested)
    } else {
      remove(child)
    }
  }
}
const pruneUnmanaged = (dst: string, paths: readonly string[], names: readonly string[]): void => {
  for (const name of entries(dst)) {
    if (names.includes(name) || paths.includes(name)) {
      continue
    }
    const child = join(dst, name)
    const nested = childPreserve(paths, name)
    if (nested.length > 0 && lstatSync(child).isDirectory()) {
      prune(child, nested)
    } else {
      remove(child)
    }
  }
}

const syncEntry = (
  src: string,
  dst: string,
  paths: readonly string[],
  options: { readonly cache: SourceContentCache | undefined; readonly pruneDst: boolean },
): void => {
  const { cache, pruneDst } = options
  const metadata = sourceMetadata(src)
  if (!metadata.isDirectory()) {
    if (identical(src, metadata, dst, cache)) {
      return
    }
    mkdirSync(dirname(dst), { recursive: true })
    remove(dst)
    copyFileSync(src, dst)
    fmodeAndTimes(dst, metadata)
    return
  }
  if (pruneDst) {
    try {
      if (!lstatSync(dst).isDirectory()) {
        remove(dst)
      }
    } catch (error) {
      if (!missing(error)) {
        throw error
      }
    }
    mkdirSync(dst, { recursive: true })
  }
  const names = Arr.filter(readdirSync(src), (name) => !isIgnoredSyncEntry(name))
  if (pruneDst) {
    pruneUnmanaged(dst, paths, names)
  }
  for (const name of names) {
    if (paths.includes(name)) {
      continue
    }
    syncEntry(join(src, name), join(dst, name), childPreserve(paths, name), { cache, pruneDst: true })
  }
}
const fmodeAndTimes = (path: string, metadata: Stats): void => {
  // copy2 preserves permission bits and timestamps, including when the umask is restrictive.
  chmodSync(path, metadata.mode & 0o7777)
  utimesSync(path, metadata.atime, metadata.mtime)
}

const textMatches = (path: string, content: string, mode: number): boolean => {
  try {
    const metadata = lstatSync(path)
    return (
      metadata.isFile() && (metadata.mode & 0o777) === mode && readFileSync(path).equals(Buffer.from(content))
    )
  } catch {
    return false
  }
}
const createTemp = (path: string, mode: number): { fd: number; temp: string } => {
  const nonce = Date.now().toString(16)
  for (let attempt = 0; attempt < 16; attempt++) {
    const temp = join(dirname(path), `.${basename(path) || "config"}.${process.pid}.${nonce}-${attempt}.tmp`)
    try {
      return { fd: openSync(temp, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL, mode), temp }
    } catch (error) {
      if (!(typeof error === "object" && error !== null && "code" in error && error.code === "EEXIST")) {
        throw error
      }
    }
  }
  throw new Error(`create temporary config near ${path} (name collision)`)
}

const writeText = (path: string, content: string, mode: number): void => {
  if (textMatches(path, content, mode)) {
    return
  }
  mkdirSync(dirname(path), { recursive: true })
  const created = createTemp(path, mode)
  let fd: number | undefined = created.fd
  const temp = created.temp
  try {
    const bytes = Buffer.from(content)
    let offset = 0
    while (offset < bytes.length) {
      const written = writeSync(fd, bytes, offset, bytes.length - offset)
      if (written === 0) {
        throw new Error(`write ${temp} (zero bytes written)`)
      }
      offset += written
    }
    fchmodSync(fd, mode)
    fsyncSync(fd)
    closeSync(fd)
    fd = undefined
    renameSync(temp, path)
  } catch (error) {
    if (fd !== undefined) {
      try {
        closeSync(fd)
      } catch {
        // Preserve the original write failure.
      }
    }
    try {
      unlinkSync(temp)
    } catch {
      // Preserve the original write failure.
    }
    throw error
  }
}

export const FilesPosix = Layer.succeed(
  Files,
  Files.of({
    isSymlink: Effect.fn("Files.isSymlink")((path: string) =>
      Effect.try({
        try: () => {
          try {
            return lstatSync(path).isSymbolicLink()
          } catch (error) {
            if (missing(error)) {
              return false
            }
            throw error
          }
        },
        catch: (cause) => FilesError.make({ operation: "isSymlink", path, cause }),
      }),
    ),
    rmEntry: Effect.fn("Files.rmEntry")((path: string) =>
      Effect.try({
        try: () => {
          remove(path)
        },
        catch: (cause) => FilesError.make({ operation: "rmEntry", path, cause }),
      }),
    ),
    isIdenticalFile: Effect.fn("Files.isIdenticalFile")(
      (src: string, metadata: Stats, dst: string, cache?: SourceContentCache) =>
        Effect.try({
          try: () => identical(src, metadata, dst, cache),
          catch: (cause) => FilesError.make({ operation: "isIdenticalFile", path: src, cause }),
        }),
    ),
    syncManagedTree: Effect.fn("Files.syncManagedTree")(
      (src: string, dst: string, paths: readonly string[] = [], cache?: SourceContentCache) =>
        Effect.try({
          try: () => {
            syncEntry(
              src,
              dst,
              filter(paths, (item) => item.length > 0),
              {
                cache,
                pruneDst: true,
              },
            )
          },
          catch: (cause) => FilesError.make({ operation: "syncManagedTree", path: src, cause }),
        }),
    ),
    syncManagedChildren: Effect.fn("Files.syncManagedChildren")(
      (src: string, dst: string, paths: readonly string[] = [], cache?: SourceContentCache) =>
        Effect.try({
          try: () => {
            syncEntry(
              src,
              dst,
              filter(paths, (item) => item.length > 0),
              {
                cache,
                pruneDst: false,
              },
            )
          },
          catch: (cause) => FilesError.make({ operation: "syncManagedChildren", path: src, cause }),
        }),
    ),
    existingFileMode: Effect.fn("Files.existingFileMode")((path: string) =>
      Effect.sync(() => {
        try {
          const metadata = lstatSync(path)
          return metadata.isFile() ? metadata.mode & 0o777 : OUTPUT_MODE
        } catch {
          return OUTPUT_MODE
        }
      }),
    ),
    syncTextFile: Effect.fn("Files.syncTextFile")((path: string, content: string, mode = OUTPUT_MODE) =>
      Effect.try({
        try: () => {
          writeText(path, content, mode)
        },
        catch: (cause) => FilesError.make({ operation: "syncTextFile", path, cause }),
      }),
    ),
    isExecutable: Effect.fn("Files.isExecutable")((path: string) =>
      Effect.sync(() => {
        try {
          const metadata = statSync(path)
          return metadata.isFile() && (metadata.mode & 0o111) !== 0
        } catch {
          return false
        }
      }),
    ),
  }),
)
