import { Array as Arr, Effect, FileSystem, Option, Order, Path, Schema, String as Str } from "effect"

import type { StaticRelease } from "#domain/HarnessAdapters"
import { StaticReleaseManifest } from "#domain/ReleaseManifest"
import { Host } from "#platform/Host"
import { Links } from "#platform/Links"
import { Lock } from "#platform/Lock"
import { RunningExecutables } from "#platform/RunningExecutables"
import { Http } from "#services/Http"
import { Output } from "#services/Output"

export class StaticReleaseError extends Schema.TaggedError<
  StaticReleaseError,
  { readonly brand: unique symbol }
>()("StaticReleaseError", { message: Schema.String, cause: Schema.optional(Schema.Defect()) }) {}

const failure = (message: string, cause?: unknown) => StaticReleaseError.make({ message, cause })
const versionsPath = (path: Path.Path, home: string, release: StaticRelease) =>
  path.join(home, ...release.installSegments, "_versions")
const numericVersion = /^\d+(?:\.\d+)*$/u

export const currentStaticRelease = Effect.fn("StaticRelease.current")(function* (
  release: StaticRelease,
  home: string,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const versions = versionsPath(path, home, release)
  return yield* Effect.gen(function* () {
    const link = path.join(versions, "current")
    if ((yield* fs.lstat(link)).type !== "SymbolicLink") {
      return Option.none<string>()
    }
    const root = yield* fs.realPath(versions)
    const version = yield* fs.realPath(link)
    if (path.dirname(version) !== root || !numericVersion.test(path.basename(version))) {
      return Option.none<string>()
    }
    const executable = yield* fs.realPath(path.join(version, ...release.executableSegments))
    const relative = path.relative(version, executable)
    if (
      relative === "" ||
      relative === ".." ||
      Str.startsWith(`..${path.sep}`)(relative) ||
      path.isAbsolute(relative)
    ) {
      return Option.none<string>()
    }
    const stat = yield* fs.stat(executable)
    return stat.type === "File" && (stat.mode & 0o111) !== 0 ? Option.some(executable) : Option.none<string>()
  }).pipe(Effect.orElseSucceed(() => Option.none<string>()))
})

interface TarEntry {
  readonly name: string
  readonly type: string
  readonly link: string
  readonly mode: number
  readonly data: Uint8Array
}
const text = (bytes: Uint8Array) => Str.replace(/\0.*$/su, "")(new TextDecoder().decode(bytes))
const octal = (bytes: Uint8Array) => Number.parseInt(Str.trim(text(bytes)) || "0", 8)
const safeName = (name: string) =>
  name !== "" && !Str.startsWith("/")(name) && !Str.split(name, "/").includes("..")

const parsePax = (data: Uint8Array, pax: Record<string, string>): void => {
  let index = 0
  while (index < data.length) {
    const space = data.indexOf(32, index)
    if (space === -1) {
      throw new Error("invalid pax header")
    }
    const length = Number(text(data.subarray(index, space)))
    if (!Number.isSafeInteger(length) || length <= space - index + 1 || index + length > data.length) {
      throw new Error("invalid pax header")
    }
    const record = new TextDecoder().decode(data.subarray(space + 1, index + length - 1))
    const equals = Str.indexOf("=")(record)
    if (Option.isSome(equals) && equals.value > 0) {
      pax[Str.slice(0, equals.value)(record)] = Str.slice(equals.value + 1)(record)
    }
    index += length
  }
}

const tarSize = (header: Uint8Array, offset: number, length: number): number => {
  const size = octal(header.subarray(124, 136))
  if (!Number.isSafeInteger(size) || size < 0 || offset + 512 + size > length) {
    throw new Error("invalid tar entry size")
  }
  const expected = octal(header.subarray(148, 156))
  const checksum = header.reduce((sum, byte, index) => sum + (index >= 148 && index < 156 ? 32 : byte), 0)
  if (checksum !== expected) {
    throw new Error("invalid tar checksum")
  }
  return size
}

// Parse and validate the whole archive before writing anything. Never follow an archive symlink.
const parseTar = (bytes: Uint8Array): TarEntry[] => {
  const entries: TarEntry[] = []
  let offset = 0
  let longName = ""
  let longLink = ""
  let pax: Record<string, string> = {}
  while (offset + 512 <= bytes.length) {
    const header = bytes.subarray(offset, offset + 512)
    if (header.every((byte) => byte === 0)) {
      break
    }
    const size = tarSize(header, offset, bytes.length)
    const type = text(header.subarray(156, 157)) || "0"
    const data = bytes.subarray(offset + 512, offset + 512 + size)
    offset += 512 + Math.ceil(size / 512) * 512
    if (type === "L") {
      longName = text(data)
      continue
    }
    if (type === "K") {
      longLink = text(data)
      continue
    }
    if (type === "x" || type === "g") {
      parsePax(data, pax)
      continue
    }
    const prefix = text(header.subarray(345, 500))
    const baseName = text(header.subarray(0, 100))
    const name = pax["path"] ?? (longName || (prefix === "" ? baseName : `${prefix}/${baseName}`))
    const link = pax["linkpath"] ?? (longLink || text(header.subarray(157, 257)))
    longName = ""
    longLink = ""
    pax = {}
    if (!safeName(name) || !["0", "5", "1", "2"].includes(type)) {
      throw new Error(`unsafe tar entry: ${name}`)
    }
    entries.push({
      name: Str.replace(/\/$/u, "")(name),
      type,
      link,
      mode: octal(header.subarray(100, 108)),
      data,
    })
  }
  return entries
}

const validateEntries = (entries: readonly TarEntry[], stage: string, path: Path.Path): TarEntry[] => {
  const linkEntries: TarEntry[] = []
  for (const entry of entries) {
    if (entry.type === "1" || entry.type === "2") {
      linkEntries.push(entry)
    }
  }
  const links = new Set(Arr.map((entry: TarEntry) => path.normalize(entry.name))(linkEntries))
  for (const entry of entries) {
    const dest = path.join(stage, entry.name)
    const parts = Str.split(path.normalize(entry.name), path.sep)
    for (let i = 1; i < parts.length; i++) {
      if (links.has(Arr.join(parts.slice(0, i), path.sep))) {
        throw new Error(`unsafe tar entry: ${entry.name}`)
      }
    }
    if (entry.type === "1" || entry.type === "2") {
      const base = entry.type === "1" ? stage : path.dirname(dest)
      const relative = path.relative(stage, path.resolve(base, entry.link))
      if (path.isAbsolute(entry.link) || relative === ".." || Str.startsWith(`..${path.sep}`)(relative)) {
        throw new Error(`unsafe tar link: ${entry.name}`)
      }
      const targetParts = Str.split(relative, path.sep)
      for (let i = 1; i <= targetParts.length; i++) {
        if (links.has(Arr.join(targetParts.slice(0, i), path.sep))) {
          throw new Error(`unsafe tar link: ${entry.name}`)
        }
      }
    }
  }
  return linkEntries
}

const extract = Effect.fn("StaticRelease.extract")(function* (archive: Uint8Array, stage: string) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const bytes = yield* Effect.tryPromise({
    try: () => {
      const blob = new Blob([new Uint8Array(archive)])
      const stream = blob.stream().pipeThrough(new DecompressionStream("gzip"))
      return new Response(stream).arrayBuffer().then((buffer) => new Uint8Array(buffer))
    },
    catch: (cause) => failure("archive extraction failed", cause),
  })
  const entries = yield* Effect.try({
    try: () => parseTar(bytes),
    catch: (cause) => failure("archive extraction failed", cause),
  })
  const linkEntries = yield* Effect.try({
    try: () => validateEntries(entries, stage, path),
    catch: (cause) => failure("archive extraction failed", cause),
  })
  for (const entry of entries) {
    if (entry.type !== "0" && entry.type !== "5") {
      continue
    }
    const dest = path.join(stage, entry.name)
    if (entry.type === "5") {
      yield* fs.makeDirectory(dest, { recursive: true })
    } else {
      yield* fs.makeDirectory(path.dirname(dest), { recursive: true })
      yield* fs.writeFile(dest, entry.data, { mode: entry.mode & 0o777 })
      yield* fs.chmod(dest, entry.mode & 0o777)
    }
  }
  for (const entry of linkEntries) {
    const dest = path.join(stage, entry.name)
    yield* fs.makeDirectory(path.dirname(dest), { recursive: true })
    yield* entry.type === "2" ? fs.symlink(entry.link, dest) : fs.link(path.join(stage, entry.link), dest)
  }
})

const publishMan = Effect.fn("StaticRelease.publishMan")(function* (
  release: StaticRelease,
  home: string,
  version: string,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const links = yield* Links
  const output = yield* Output
  const versions = versionsPath(path, home, release)
  const versionDir = path.join(versions, version)
  const current = path.join(versions, "current")
  if (release.manSegments === null || release.manDestSegments === null) {
    return
  }
  const source = path.join(versionDir, ...release.manSegments)
  if (!(yield* fs.exists(source))) {
    return
  }
  const dest = path.join(home, ...release.manDestSegments)
  yield* fs.makeDirectory(dest, { recursive: true })
  const names: string[] = []
  for (const name of yield* fs.readDirectory(source)) {
    const stat = yield* fs.stat(path.join(source, name)).pipe(Effect.option)
    if (Option.isSome(stat) && stat.value.type === "File") {
      names.push(name)
    }
  }
  for (const entry of yield* fs.readDirectoryEntries(dest)) {
    if (entry.type !== "SymbolicLink" || names.includes(entry.name)) {
      continue
    }
    const target = yield* fs.readLink(path.join(dest, entry.name))
    if (Str.startsWith(`${versions}${path.sep}`)(target)) {
      yield* fs.remove(path.join(dest, entry.name), { force: true })
    }
  }
  for (const name of Arr.sort(names, Order.String)) {
    const link = path.join(dest, name)
    const target = path.join(current, ...release.manSegments, name)
    yield* links
      .replaceLink(link, target)
      .pipe(Effect.catch((error) => output.warn(`man page conflict at ${link}: ${String(error)}`)))
  }
})

const publish = Effect.fn("StaticRelease.publish")(function* (
  release: StaticRelease,
  home: string,
  version: string,
  running: Option.Option<ReadonlySet<string>> | undefined,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const links = yield* Links
  const versions = versionsPath(path, home, release)
  const current = path.join(versions, "current")
  const old = yield* links.readLinkTarget(current)
  if (Option.isNone(old) || old.value !== version) {
    if (Option.isSome(old)) {
      yield* links.replaceLink(path.join(versions, "previous"), old.value)
    }
    yield* links.replaceLink(current, version)
  }
  // Prune only with a complete process listing: an unknown listing keeps every version,
  // and a version some process is executing from survives until it exits.
  const processes = running ?? (yield* (yield* RunningExecutables).get)
  if (Option.isSome(processes)) {
    const previous = yield* links.readLinkTarget(path.join(versions, "previous"))
    const keep = new Set([version, ...(Option.isSome(previous) ? [path.basename(previous.value)] : [])])
    for (const entry of yield* fs.readDirectoryEntries(versions)) {
      if (entry.type !== "Directory" || !numericVersion.test(entry.name) || keep.has(entry.name)) {
        continue
      }
      const candidate = path.join(versions, entry.name)
      const real = yield* fs.realPath(candidate).pipe(Effect.orElseSucceed(() => candidate))
      if (!Arr.some([...processes.value], (p) => p === real || Str.startsWith(`${real}/`)(p))) {
        yield* fs.remove(candidate, { recursive: true, force: true })
      }
    }
  }
  yield* publishMan(release, home, version)
})

const install = Effect.fn("StaticRelease.install")(function* (
  versions: string,
  version: string,
  asset: { readonly url: string; readonly sha256: string },
  timeoutMs: number,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const http = yield* Http
  yield* Effect.scoped(
    Effect.gen(function* () {
      const stage = yield* fs.makeTempDirectoryScoped({ directory: versions, prefix: ".stage-" })
      const archive = yield* http.getOk(asset.url, timeoutMs, "download failed")
      const digest = yield* Effect.tryPromise({
        try: () => crypto.subtle.digest("SHA-256", new Uint8Array(archive)),
        catch: (cause) => failure("checksum failed", cause),
      })
      const actual = Arr.join(
        Array.from(new Uint8Array(digest), (byte) => Str.padStart(2, "0")(byte.toString(16))),
        "",
      )
      if (actual !== asset.sha256) {
        return yield* failure(`checksum mismatch for release-${version}.tar.gz`)
      }
      yield* extract(archive, stage).pipe(
        Effect.timeoutOrElse({
          duration: Math.max(0, timeoutMs),
          orElse: () => Effect.fail(failure("archive extraction timed out")),
        }),
      )
      yield* fs.writeFileString(path.join(stage, "distribution"), "curl-bash\n")
      const versionDir = path.join(versions, version)
      yield* fs.remove(versionDir, { recursive: true, force: true })
      yield* fs.rename(stage, versionDir)
    }),
  )
})

const fetchManifest = Effect.fn("StaticRelease.fetchManifest")(function* (url: string, timeoutMs: number) {
  const http = yield* Http
  const bytes = yield* http.getOk(url, timeoutMs, "release manifest fetch failed")
  const parsed = yield* Schema.decodeEffect(Schema.fromJsonString(Schema.Unknown))(
    new TextDecoder().decode(bytes),
  ).pipe(Effect.mapError((cause) => failure("release manifest parse failed", cause)))
  return yield* Schema.decodeUnknownEffect(StaticReleaseManifest)(parsed).pipe(
    Effect.mapError((cause) => failure("invalid release manifest", cause)),
  )
})

const locked = Effect.fn("StaticRelease.locked")(function* (
  release: StaticRelease,
  home: string,
  timeoutMs: number,
  running?: Option.Option<ReadonlySet<string>>,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const host = yield* Host
  const versions = versionsPath(path, home, release)
  yield* fs.makeDirectory(versions, { recursive: true })
  const manifest = yield* fetchManifest(release.manifestUrl, timeoutMs)
  if (manifest.version === "." || manifest.version === "..") {
    return yield* failure("invalid release manifest version")
  }
  const normalizedArch = Str.toLowerCase(Str.trim(host.arch))
  const arch = ["aarch64", "arm64"].includes(normalizedArch)
    ? "arm64"
    : ["x86_64", "amd64", "x64"].includes(normalizedArch)
      ? "x64"
      : null
  if (arch === null) {
    return yield* failure(`unsupported architecture: ${host.arch}`)
  }
  const platform = `${host.platform}-${arch}`
  const target = release.targets[platform]
  if (target === undefined) {
    return yield* failure(`static release has no target for ${platform}`)
  }
  const asset = manifest.platforms[target]
  if (asset === undefined) {
    return yield* failure(`static release ${manifest.version} missing platform ${target}`)
  }
  const versionDir = path.join(versions, manifest.version)
  const executable = path.join(versionDir, ...release.executableSegments)
  const isExecutable = (file: string) =>
    fs.stat(file).pipe(
      Effect.map((stat) => stat.type === "File" && (stat.mode & 0o111) !== 0),
      Effect.orElseSucceed(() => false),
    )
  if (!(yield* isExecutable(executable))) {
    yield* install(versions, manifest.version, asset, timeoutMs)
  }
  if (!(yield* isExecutable(executable))) {
    return yield* failure(`static release ${manifest.version} has no executable ${executable}`)
  }
  yield* publish(release, home, manifest.version, running)
  return executable
})

export const refreshStaticRelease = Effect.fn("StaticRelease.refresh")(function* (
  release: StaticRelease,
  home: string,
  timeoutMs: number,
  running?: Option.Option<ReadonlySet<string>>,
) {
  const path = yield* Path.Path
  const lock = yield* Lock
  const output = yield* Output
  const root = path.join(home, ...release.installSegments)
  return yield* Effect.scoped(
    Effect.gen(function* () {
      const acquired = yield* lock.tryAcquireSyncLock(root, path.join(root, "lock"))
      if (Option.isNone(acquired)) {
        yield* output.warn(`refresh-packages: ${release.manifestUrl}: cache lock busy; skipping`)
        return false
      }
      yield* locked(release, home, timeoutMs, running)
      return true
    }),
  )
})

export const prepareStaticRelease = Effect.fn("StaticRelease.prepare")(function* (
  release: StaticRelease,
  home: string,
  timeoutMs: number,
) {
  const path = yield* Path.Path
  const lock = yield* Lock
  const output = yield* Output
  const root = path.join(home, ...release.installSegments)
  const acquire = Effect.gen(function* () {
    while (true) {
      const acquired = yield* lock.tryAcquireSyncLock(root, path.join(root, "lock"))
      if (Option.isSome(acquired)) {
        return
      }
      yield* Effect.sleep(25)
    }
  }).pipe(
    Effect.timeoutOrElse({
      duration: Math.max(0, timeoutMs),
      orElse: () => Effect.fail(failure(`timed out waiting for cache lock: ${path.join(root, "lock")}`)),
    }),
  )
  const prepare = Effect.scoped(
    Effect.gen(function* () {
      yield* acquire
      return yield* locked(release, home, timeoutMs)
    }),
  )
  return yield* prepare.pipe(
    Effect.catch((error) =>
      Effect.gen(function* () {
        const cached = yield* currentStaticRelease(release, home)
        if (Option.isNone(cached)) {
          return yield* error
        }
        const fs = yield* FileSystem.FileSystem
        const versions = yield* fs.realPath(versionsPath(path, home, release))
        const version = Str.split(path.relative(versions, cached.value), path.sep)[0]
        const detail = error instanceof Error ? error.message : String(error)
        yield* output.warn(`static release lookup failed (${detail}); using cached ${version}`)
        return cached.value
      }),
    ),
  )
})
