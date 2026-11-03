import { Array as Arr, Effect, FileSystem, Option, Path, Schema, String as Str } from "effect"

import { detailFromOutput } from "#domain/ProcessDetail"
import { Host } from "#platform/Host"
import { Links } from "#platform/Links"
import { Lock } from "#platform/Lock"
import { Proc } from "#platform/Proc"
import { RunningExecutables } from "#platform/RunningExecutables"
import { Http } from "#services/Http"
import { Output } from "#services/Output"

export interface NpmPackageSpec {
  readonly tool: string
  readonly package: string
  readonly bin: string
  readonly env?: Readonly<Record<string, string>> | undefined
}
export interface PreparePackageOptions {
  readonly home: string
  readonly cacheHome?: string | undefined
  readonly timeoutMs?: number | undefined
  /** Registry base URL from npm config, resolved once per run; absent means `npm view` resolves. */
  readonly registry?: string | undefined
  /** Real paths of running executables, scanned once per run by the caller; scanned here when absent. */
  readonly running?: Option.Option<ReadonlySet<string>> | undefined
}
export interface NpmCacheLayout {
  readonly toolCache: string
  readonly versionsDir: string
  readonly currentLink: string
  readonly previousLink: string
  readonly lockFile: string
}
export interface PreparedNpmPackage {
  readonly layout: NpmCacheLayout
  readonly resolvedVersion: string
  readonly currentBin: string
}
export class NpmCacheError extends Schema.TaggedError<NpmCacheError, { readonly brand: unique symbol }>()(
  "NpmCacheError",
  {
    message: Schema.String,
  },
) {}

const versionPattern = /^\d+\.\d+\.\d+(-[\w.]+)?(\+[\w.]+)?$/u
const component = /^[A-Za-z0-9._~-]+$/u
const packagePattern = /^(?:@[A-Za-z0-9._~-]+\/)?[A-Za-z0-9._~-]+$/u
const fail = (message: string) => NpmCacheError.make({ message })
const validComponent = (s: string) => component.test(s) && s !== "." && s !== ".."
const validate = (spec: NpmPackageSpec) => {
  if (!validComponent(spec.tool)) {
    return `invalid tool: ${spec.tool}`
  }
  if (!validComponent(spec.bin)) {
    return `invalid bin: ${spec.bin}`
  }
  if (
    !packagePattern.test(spec.package) ||
    Arr.some(Str.split(spec.package, "/"), (part) => part === "." || part === "..")
  ) {
    return `invalid package: ${spec.package}`
  }
  return undefined
}

const join = (...parts: string[]) => Str.replaceAll(/\/{2,}/gu, "/")(Arr.join(parts, "/"))

export const npmCacheLayout = (spec: NpmPackageSpec, options: PreparePackageOptions): NpmCacheLayout => {
  const toolCache = join(options.cacheHome ?? `${options.home}/.cache`, "npm-tools", spec.tool)
  const key = Str.slice(0, 16)(new Bun.CryptoHasher("sha256").update(spec.package).digest("hex"))
  const root = join(toolCache, "packages", key)
  return {
    toolCache,
    versionsDir: join(root, "versions"),
    currentLink: join(root, "current"),
    previousLink: join(root, "previous"),
    lockFile: join(toolCache, "lock"),
  }
}
const binPath = (root: string, bin: string) => `${root}/node_modules/.bin/${bin}`
const Manifest = Schema.Struct({ name: Schema.String, version: Schema.String })
const decodeManifest = Schema.decodeUnknownEffect(Schema.fromJsonString(Manifest))

const executable = Effect.fn("NpmCache.executable")(function* (file: string) {
  const fs = yield* FileSystem.FileSystem
  const stat = yield* fs.stat(file).pipe(Effect.option)
  return Option.isSome(stat) && stat.value.type === "File" && (stat.value.mode & 0o111) !== 0
})
const matches = Effect.fn("NpmCache.matches")(function* (
  root: string,
  spec: NpmPackageSpec,
  version: string,
) {
  const fs = yield* FileSystem.FileSystem
  const file = `${root}/node_modules/${spec.package}/package.json`
  const text = yield* fs.readFileString(file).pipe(Effect.option)
  if (Option.isNone(text)) {
    return false
  }
  const manifest = yield* decodeManifest(text.value).pipe(Effect.option)
  return Option.isSome(manifest) && manifest.value.name === spec.package && manifest.value.version === version
})

export const currentCachedPackage = Effect.fn("NpmCache.currentCachedPackage")(function* (
  spec: NpmPackageSpec,
  options: PreparePackageOptions,
) {
  const host = yield* Host
  const path = yield* Path.Path
  const links = yield* Links
  const layout = npmCacheLayout(spec, { ...options, cacheHome: options.cacheHome ?? host.cacheHome })
  if (validate(spec) !== undefined) {
    return Option.none<PreparedNpmPackage>()
  }
  const read = yield* links.readLinkTarget(layout.currentLink).pipe(Effect.option)
  if (Option.isNone(read) || Option.isNone(read.value)) {
    return Option.none<PreparedNpmPackage>()
  }
  const target = read.value.value
  const root = path.resolve(path.dirname(layout.currentLink), target)
  const version = path.basename(target)
  if (!(yield* executable(binPath(root, spec.bin))) || !(yield* matches(root, spec, version))) {
    return Option.none<PreparedNpmPackage>()
  }
  return Option.some<PreparedNpmPackage>({
    layout,
    resolvedVersion: version,
    currentBin: binPath(layout.currentLink, spec.bin),
  })
})

const reclaimStages = Effect.fn("NpmCache.reclaimStages")(function* (layout: NpmCacheLayout) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const host = yield* Host
  const stages = yield* fs.readDirectory(layout.versionsDir).pipe(Effect.orElseSucceed(() => []))
  for (const name of stages) {
    const match = /^\.stage-(\d+)-/u.exec(name)
    if (match?.[1] === undefined || Number(match[1]) === 0) {
      continue
    }
    if (!(yield* host.isPidAlive(Number(match[1])))) {
      yield* fs
        .remove(path.join(layout.versionsDir, name), { recursive: true, force: true })
        .pipe(Effect.ignore)
    }
  }
})

const installStage = Effect.fn("NpmCache.installStage")(function* (
  spec: NpmPackageSpec,
  version: string,
  stage: string,
  timeoutMs: number,
) {
  const proc = yield* Proc
  const install = yield* proc.run(
    [
      "npm",
      "install",
      "--prefix",
      stage,
      "--no-save",
      "--no-package-lock",
      "--no-audit",
      "--no-fund",
      "--loglevel=error",
      `${spec.package}@${version}`,
    ],
    { timeoutMs },
  )
  if (install.exitCode !== 0 || install.timedOut || install.outputLimited) {
    return yield* fail(`npm install failed: ${detailFromOutput(install.stdout, install.stderr)}`)
  }
  const binary = binPath(stage, spec.bin)
  if (!(yield* executable(binary))) {
    return yield* fail(`installed package has no executable bin: ${spec.bin}`)
  }
  if (!(yield* matches(stage, spec, version))) {
    return yield* fail(`installed package identity mismatch: ${spec.package}@${version}`)
  }
  const smoke = yield* proc.run([binary, "--version"], { cwd: stage, timeoutMs })
  if (smoke.exitCode !== 0 || smoke.timedOut || smoke.outputLimited) {
    return yield* fail(
      `installed package smoke check failed: ${detailFromOutput(smoke.stdout, smoke.stderr)}`,
    )
  }
})

const ensureInstalled = Effect.fn("NpmCache.ensureInstalled")(function* (
  spec: NpmPackageSpec,
  layout: NpmCacheLayout,
  version: string,
  timeoutMs: number,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const host = yield* Host
  const versionDir = path.join(layout.versionsDir, version)
  if (yield* executable(binPath(versionDir, spec.bin))) {
    if (!(yield* matches(versionDir, spec, version))) {
      return yield* fail(`cached package identity mismatch: ${version}`)
    }
  } else {
    if (yield* fs.exists(versionDir)) {
      return yield* fail(`cached package is incomplete: ${version}`)
    }
    yield* reclaimStages(layout)
    const stage = yield* fs.makeTempDirectory({
      directory: layout.versionsDir,
      prefix: `.stage-${host.pid}-`,
    })
    yield* Effect.gen(function* () {
      yield* installStage(spec, version, stage, timeoutMs)
      yield* fs.rename(stage, versionDir)
    }).pipe(Effect.ensuring(fs.remove(stage, { recursive: true, force: true }).pipe(Effect.ignore)))
  }
})

const rotateAndPrune = Effect.fn("NpmCache.rotateAndPrune")(function* (
  layout: NpmCacheLayout,
  version: string,
  running: Option.Option<ReadonlySet<string>> | undefined,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const links = yield* Links
  const target = path.join("versions", version)
  const old = yield* links.readLinkTarget(layout.currentLink)
  if (Option.isNone(old) || old.value !== target) {
    if (Option.isSome(old)) {
      yield* links.replaceLink(layout.previousLink, old.value)
    }
    yield* links.replaceLink(layout.currentLink, target)
  }
  const processes = running ?? (yield* (yield* RunningExecutables).get)
  if (Option.isSome(processes)) {
    yield* reclaimStages(layout)
    const previous = yield* links.readLinkTarget(layout.previousLink)
    const keep = new Set([version, ...(Option.isSome(previous) ? [path.basename(previous.value)] : [])])
    const entries = yield* fs.readDirectory(layout.versionsDir).pipe(Effect.orElseSucceed(() => []))
    for (const entry of entries) {
      if (keep.has(entry) || Str.startsWith(".stage")(entry)) {
        continue
      }
      const candidate = path.join(layout.versionsDir, entry)
      const real = yield* fs.realPath(candidate).pipe(Effect.orElseSucceed(() => path.resolve(candidate)))
      if (Arr.some([...processes.value], (p) => p === real || Str.startsWith(`${real}/`)(p))) {
        continue
      }
      yield* fs.remove(candidate, { recursive: true, force: true }).pipe(Effect.ignore)
    }
  }
})

const Latest = Schema.Struct({ version: Schema.String })
const decodeLatest = Schema.decodeUnknownEffect(Schema.fromJsonString(Latest))

const viewLatest = Effect.fn("NpmCache.viewLatest")(function* (spec: NpmPackageSpec, timeoutMs: number) {
  const proc = yield* Proc
  const resolved = yield* proc.run(["npm", "view", `${spec.package}@latest`, "version"], { timeoutMs })
  if (resolved.exitCode !== 0 || resolved.timedOut || resolved.outputLimited) {
    return yield* fail(`could not resolve ${spec.package}@latest`)
  }
  return Str.trim(Str.replaceAll(/[\r\n]/gu, "")(resolved.stdout))
})

// The registry's `/<package>/latest` document is a few kilobytes; `npm view` boots npm and
// downloads the full packument. Any registry failure (auth, proxy, outage) falls back to
// `npm view`, which applies the complete npm configuration.
const resolveLatest = Effect.fn("NpmCache.resolveLatest")(function* (
  spec: NpmPackageSpec,
  registry: string | undefined,
  timeoutMs: number,
) {
  if (registry === undefined) {
    return yield* viewLatest(spec, timeoutMs)
  }
  const http = yield* Http
  const url = `${Str.replace(/\/*$/u, "/")(registry)}${Str.replace("/", "%2f")(spec.package)}/latest`
  return yield* http.getOk(url, timeoutMs, `could not resolve ${spec.package}@latest`).pipe(
    Effect.flatMap((bytes) => decodeLatest(new TextDecoder().decode(bytes))),
    Effect.map((latest) => latest.version),
    Effect.catch(() => viewLatest(spec, timeoutMs)),
  )
})

const prepareLocked = Effect.fn("NpmCache.prepareLocked")(function* (
  spec: NpmPackageSpec,
  options: PreparePackageOptions,
  layout: NpmCacheLayout,
) {
  const timeoutMs = options.timeoutMs ?? 120_000
  const version = yield* resolveLatest(spec, options.registry, timeoutMs)
  if (!versionPattern.test(version)) {
    return yield* fail(`invalid resolved version: ${version}`)
  }
  yield* ensureInstalled(spec, layout, version, timeoutMs)
  yield* rotateAndPrune(layout, version, options.running)
  const currentBin = binPath(layout.currentLink, spec.bin)
  if (!(yield* executable(currentBin))) {
    return yield* fail(`current package has no executable bin: ${spec.bin}`)
  }
  return { layout, resolvedVersion: version, currentBin }
})

export const prepareNpmPackage = Effect.fn("NpmCache.prepareNpmPackage")(function* (
  spec: NpmPackageSpec,
  options: PreparePackageOptions,
) {
  const invalid = validate(spec)
  if (invalid !== undefined) {
    return yield* fail(invalid)
  }
  const host = yield* Host
  const fs = yield* FileSystem.FileSystem
  const lock = yield* Lock
  const output = yield* Output
  const layout = npmCacheLayout(spec, { ...options, cacheHome: options.cacheHome ?? host.cacheHome })
  yield* fs.makeDirectory(layout.versionsDir, { recursive: true })
  return yield* Effect.scoped(
    Effect.gen(function* () {
      const deadline = (yield* host.now) + (options.timeoutMs ?? 120_000)
      while (true) {
        const held = yield* lock.tryAcquireSyncLock(layout.toolCache, layout.lockFile)
        if (Option.isSome(held)) {
          break
        }
        if ((yield* host.now) >= deadline) {
          return yield* fail(`timed out waiting for cache lock: ${layout.lockFile}`)
        }
        yield* Effect.sleep("25 millis")
      }
      return yield* prepareLocked(spec, options, layout).pipe(
        Effect.catch((error) =>
          Effect.gen(function* () {
            const cached = yield* currentCachedPackage(spec, options)
            if (Option.isNone(cached)) {
              return yield* error
            }
            yield* output.warn(
              `${spec.package} unavailable (${error.message}); using cached ${spec.tool}@${cached.value.resolvedVersion}`,
            )
            return cached.value
          }),
        ),
      )
    }),
  )
})

export const refreshNpmPackage = Effect.fn("NpmCache.refreshNpmPackage")(function* (
  spec: NpmPackageSpec,
  options: PreparePackageOptions,
) {
  const invalid = validate(spec)
  if (invalid !== undefined) {
    return yield* fail(invalid)
  }
  const host = yield* Host
  const fs = yield* FileSystem.FileSystem
  const lock = yield* Lock
  const output = yield* Output
  const layout = npmCacheLayout(spec, { ...options, cacheHome: options.cacheHome ?? host.cacheHome })
  return yield* Effect.scoped(
    Effect.gen(function* () {
      const held = yield* lock.tryAcquireSyncLock(layout.toolCache, layout.lockFile)
      if (Option.isNone(held)) {
        yield* output.warn(`refresh-packages: ${spec.tool}: cache lock busy; skipping`)
        return false
      }
      yield* fs.makeDirectory(layout.versionsDir, { recursive: true })
      yield* prepareLocked(spec, options, layout)
      return true
    }),
  )
})
