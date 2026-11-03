import { Array as Arr, Effect, FileSystem, Option, String as Str } from "effect"

import { harnessFromAdapter } from "#domain/Harness"
import { HARNESS_ADAPTERS } from "#domain/HarnessAdapters"
import type { StaticRelease } from "#domain/HarnessAdapters"
import { joinPath } from "#domain/PathText"
import { TOOL_LAUNCHERS } from "#domain/ToolLaunchers"
import { refreshNpmPackage } from "#packages/NpmCache"
import type { NpmPackageSpec } from "#packages/NpmCache"
import { refreshStaticRelease } from "#packages/StaticRelease"
import { Proc } from "#platform/Proc"
import { RunningExecutables } from "#platform/RunningExecutables"
import { Output } from "#services/Output"
import { SyncEnv } from "#services/SyncEnv"

// Independent caches have separate locks; this bounds registry and disk load.
const REFRESH_CONCURRENCY = 4
const NPM_CONFIG_TIMEOUT_MS = 10_000

const scopeOf = (name: string): string | undefined =>
  Str.startsWith("@")(name) ? Str.split(name, "/")[0] : undefined

/**
 * Resolves each package's registry with one `npm config get` per run, honoring npmrc files,
 * `npm_config_*` variables, and `@scope:registry` overrides. A package keeps `npm view` when
 * npm reports no usable registry for it.
 */
const npmRegistries = Effect.fn("RefreshPackages.npmRegistries")(function* (packages: readonly string[]) {
  const proc = yield* Proc
  const scopes = new Set<string>()
  for (const name of packages) {
    const scope = scopeOf(name)
    if (scope !== undefined) {
      scopes.add(scope)
    }
  }
  const keys = ["registry", ...Arr.map((scope: string) => `${scope}:registry`)([...scopes])]
  const result = yield* proc
    .run(["npm", "config", "get", ...keys], { timeoutMs: NPM_CONFIG_TIMEOUT_MS })
    .pipe(Effect.option)
  const values = new Map<string, string>()
  if (Option.isSome(result) && result.value.exitCode === 0 && !result.value.timedOut) {
    for (const line of Str.split(result.value.stdout, "\n")) {
      const entry = /^([^=]+)=\s*(https?:\/\/\S+)\s*$/u.exec(line)
      if (entry?.[1] !== undefined && entry[2] !== undefined) {
        values.set(entry[1], entry[2])
      }
    }
  }
  const fallback = values.get("registry")
  return (name: string): string | undefined => {
    const scope = scopeOf(name)
    return (scope === undefined ? undefined : values.get(`${scope}:registry`)) ?? fallback
  }
})

const detail = (error: unknown): string => {
  if (error instanceof Error) {
    return error.message || error.name
  }
  return String(error)
}

const hostHarnesses = Effect.fn("RefreshPackages.hostHarnesses")(function* () {
  const env = yield* SyncEnv
  const fs = yield* FileSystem.FileSystem
  const harnesses = new Map(
    Arr.map((harness: (typeof env.harnesses)[number]) => [harness.id, harness] as const)(env.harnesses),
  )

  for (const adapter of HARNESS_ADAPTERS) {
    if (!adapter.platforms.includes(env.platform) || harnesses.has(adapter.id)) {
      continue
    }
    const wrapper = joinPath(env.paths.home, ".local", "bin", adapter.launcher.bin)
    const managed = yield* Effect.gen(function* () {
      const info = yield* fs.lstat(wrapper)
      if (info.type !== "File") {
        return false
      }
      const content = yield* fs.readFileString(wrapper)
      return Str.includes("agents-managed-wrapper:v1")(content)
    }).pipe(Effect.orElseSucceed(() => false))
    if (managed) {
      harnesses.set(adapter.id, harnessFromAdapter(adapter, env.paths.home))
    }
  }
  return harnesses
})

const refreshTargets = Effect.fn("RefreshPackages.refreshTargets")(function* () {
  const harnesses = yield* hostHarnesses()
  const packages: NpmPackageSpec[] = Arr.map((tool: (typeof TOOL_LAUNCHERS)[number]) => ({
    tool: tool.id,
    package: tool.package,
    bin: tool.bin,
  }))(TOOL_LAUNCHERS)
  const releases: { readonly name: string; readonly release: StaticRelease }[] = []
  for (const harness of harnesses.values()) {
    if (harness.launcher._tag === "StaticRelease") {
      releases.push({ name: harness.sourceName, release: harness.launcher.release })
    } else {
      packages.push({
        tool: harness.sourceName,
        package: harness.launcher.package,
        bin: harness.launcher.bin,
      })
    }
  }
  return { packages, releases }
})

export const refreshPackages = Effect.fn("RefreshPackages.refreshPackages")(function* () {
  const env = yield* SyncEnv
  const output = yield* Output
  const { packages, releases } = yield* refreshTargets()
  const registryFor = yield* npmRegistries(Arr.map((spec: NpmPackageSpec) => spec.package)(packages))
  const running = yield* (yield* RunningExecutables).get
  // A busy lock or failure warns and counts as incomplete; the run fails only when nothing completed.
  const settle = <E, R>(name: string, refresh: Effect.Effect<boolean, E, R>) =>
    refresh.pipe(
      Effect.as(true),
      Effect.catch((error) =>
        output.warn(`refresh-packages: ${name}: ${detail(error)}`).pipe(Effect.as(false)),
      ),
    )
  const options = { home: env.paths.home, timeoutMs: env.installTimeoutMs, running }
  const refreshes = [
    ...Arr.map((spec: NpmPackageSpec) =>
      settle(spec.tool, refreshNpmPackage(spec, { ...options, registry: registryFor(spec.package) })),
    )(packages),
    ...Arr.map(({ name, release }: (typeof releases)[number]) =>
      settle(name, refreshStaticRelease(release, env.paths.home, env.installTimeoutMs, running)),
    )(releases),
  ]
  const results = yield* Effect.all(refreshes, { concurrency: REFRESH_CONCURRENCY })
  return results.length > 0 && !results.includes(true) ? 1 : 0
})
