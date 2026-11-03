import { Array as Arr, Effect, FileSystem, String as Str } from "effect"

import { harnessFromAdapter } from "#domain/Harness"
import { HARNESS_ADAPTERS } from "#domain/HarnessAdapters"
import { joinPath } from "#domain/PathText"
import { TOOL_LAUNCHERS } from "#domain/ToolLaunchers"
import { refreshNpmPackage } from "#packages/NpmCache"
import { refreshStaticRelease } from "#packages/StaticRelease"
import { Output } from "#services/Output"
import { SyncEnv } from "#services/SyncEnv"

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

export const refreshPackages = Effect.fn("RefreshPackages.refreshPackages")(function* () {
  const env = yield* SyncEnv
  const output = yield* Output
  const harnesses = yield* hostHarnesses()

  const packages = Arr.map((tool: (typeof TOOL_LAUNCHERS)[number]) => ({
    tool: tool.id,
    package: tool.package,
    bin: tool.bin,
  }))(TOOL_LAUNCHERS)
  const releases = []
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

  let failures = 0
  let completed = 0
  for (const spec of packages) {
    const result = yield* refreshNpmPackage(spec, {
      home: env.paths.home,
      timeoutMs: env.installTimeoutMs,
    }).pipe(Effect.result)
    if (result._tag === "Failure") {
      failures++
      yield* output.warn(`refresh-packages: ${spec.tool}: ${detail(result.failure)}`)
    } else {
      completed++
    }
  }
  for (const { name, release } of releases) {
    const result = yield* refreshStaticRelease(release, env.paths.home, env.installTimeoutMs).pipe(
      Effect.result,
    )
    if (result._tag === "Failure") {
      failures++
      yield* output.warn(`refresh-packages: ${name}: ${detail(result.failure)}`)
    } else {
      completed++
    }
  }
  return failures > 0 && completed === 0 ? 1 : 0
})
