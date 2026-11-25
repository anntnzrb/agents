import { Effect, Option, Record as Rec } from "effect"

import type { Harness, StaticReleaseLauncher } from "#domain/Harness"
import { currentCachedPackage, prepareNpmPackage } from "#packages/NpmCache"
import type { NpmPackageSpec } from "#packages/NpmCache"
import { currentStaticRelease, prepareStaticRelease } from "#packages/StaticRelease"
import type { ExecPlan } from "#platform/Exec"
import { Host } from "#platform/Host"

export interface LaunchEnv {
  readonly home: string
  readonly rootEnv: Readonly<Record<string, string>>
  readonly installTimeoutMs: number
}

export const harnessPackageSpec = (
  harness: Harness,
  env?: Readonly<Record<string, string>>,
): NpmPackageSpec => {
  const launcher = harness.launcher
  if (launcher._tag === "StaticRelease") {
    throw new TypeError("static release has no npm specification")
  }
  return {
    tool: harness.sourceName,
    package: launcher.package,
    bin: launcher.bin,
    ...(env === undefined ? {} : { env }),
  }
}

const processEnv = (
  parent: Readonly<Record<string, string | undefined>>,
  rootEnv: Readonly<Record<string, string>>,
  overlay?: Readonly<Record<string, string>>,
): Record<string, string> => {
  const result: Record<string, string> = {}
  const defaults: Record<string, string> = {}
  for (const [key, value] of Rec.toEntries(parent)) {
    if (value !== undefined) {
      result[key] = value
    }
  }
  for (const [key, value] of Rec.toEntries(rootEnv)) {
    if (parent[key] === undefined) {
      defaults[key] = value
    }
  }
  return Object.assign(result, defaults, overlay)
}

export const launchNpmPackage = Effect.fn("Launch.launchNpmPackage")(function* (
  syncEnv: LaunchEnv,
  spec: NpmPackageSpec,
  args: readonly string[],
) {
  const host = yield* Host
  const options = { home: syncEnv.home, timeoutMs: syncEnv.installTimeoutMs }
  const cached = yield* currentCachedPackage(spec, options)
  const prepared = Option.isSome(cached) ? cached.value : yield* prepareNpmPackage(spec, options)
  return {
    executable: prepared.currentBin,
    args: [...args],
    env: processEnv(host.env, syncEnv.rootEnv, spec.env),
  } satisfies ExecPlan
})

export const launchStaticRelease = Effect.fn("Launch.launchStaticRelease")(function* (
  syncEnv: LaunchEnv,
  launcher: StaticReleaseLauncher,
  args: readonly string[],
  env?: Readonly<Record<string, string>>,
) {
  const host = yield* Host
  const cached = yield* currentStaticRelease(launcher.release, syncEnv.home)
  const executable = Option.isSome(cached)
    ? cached.value
    : yield* prepareStaticRelease(launcher.release, syncEnv.home, syncEnv.installTimeoutMs)
  return { executable, args: [...args], env: processEnv(host.env, syncEnv.rootEnv, env) } satisfies ExecPlan
})

export const launchHarness = Effect.fn("Launch.launchHarness")(function* (
  syncEnv: LaunchEnv,
  harness: Harness,
  args: readonly string[],
) {
  const launcherEnv = harness.launcher.env ?? undefined
  if (harness.launcher._tag === "StaticRelease") {
    return yield* launchStaticRelease(syncEnv, harness.launcher, args, launcherEnv)
  }
  return yield* launchNpmPackage(syncEnv, harnessPackageSpec(harness, launcherEnv), args)
})

export const harnessHasCache = Effect.fn("Launch.harnessHasCache")(function* (
  home: string,
  harness: Harness,
) {
  if (harness.launcher._tag === "StaticRelease") {
    const cached = yield* currentStaticRelease(harness.launcher.release, home)
    return Option.isSome(cached)
  }
  const cached = yield* currentCachedPackage(harnessPackageSpec(harness), { home })
  return Option.isSome(cached)
})
