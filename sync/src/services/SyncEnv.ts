import { Array as Arr, Context, Effect, FileSystem, Layer, Option, Schema } from "effect"

import { decodeRootEnv } from "#domain/Dotenv"
import { discoverHarnesses as resolveHarnesses, INSTALL_TIMEOUT_MS, syncEnvPaths } from "#domain/Harness"
import type { Harness, SyncEnvPaths } from "#domain/Harness"
import type { HostPlatform } from "#domain/HarnessAdapters"
import { HARNESS_ADAPTERS } from "#domain/HarnessAdapters"
import { joinPath } from "#domain/PathText"
import { Host } from "#platform/Host"

export class RootEnvReadError extends Schema.TaggedError<
  RootEnvReadError,
  { readonly brand: unique symbol }
>()("RootEnvReadError", { path: Schema.String, message: Schema.String, cause: Schema.Defect() }) {}

export class UnsupportedPlatformError extends Schema.TaggedError<
  UnsupportedPlatformError,
  { readonly brand: unique symbol }
>()("UnsupportedPlatformError", { message: Schema.String }) {}

export interface SyncEnvValue {
  readonly paths: SyncEnvPaths
  readonly harnesses: readonly Harness[]
  readonly platform: HostPlatform
  readonly rootEnv: Readonly<Record<string, string>>
  readonly installTimeoutMs: number
  readonly harness: (id: string) => Harness | undefined
}

export const loadRootEnv = Effect.fn("SyncEnv.loadRootEnv")(function* (path: string) {
  const fs = yield* FileSystem.FileSystem
  const content = yield* fs.readFileString(path).pipe(
    Effect.catch((error) =>
      error.reason._tag === "NotFound"
        ? Effect.succeed(null)
        : Effect.fail(
            RootEnvReadError.make({
              path,
              message: `failed to read root environment file ${path}`,
              cause: error,
            }),
          ),
    ),
  )
  return decodeRootEnv(content)
})

export const discoverHarnesses = Effect.fn("SyncEnv.discoverHarnesses")(function* (
  home: string,
  harnessesHome: string,
  platform: HostPlatform,
) {
  const fs = yield* FileSystem.FileSystem
  const directories: string[] = []
  for (const adapter of HARNESS_ADAPTERS) {
    const info = yield* fs.stat(joinPath(harnessesHome, adapter.id)).pipe(Effect.orElseSucceed(() => null))
    if (info?.type === "Directory") {
      directories.push(adapter.id)
    }
  }
  return resolveHarnesses(home, directories, platform)
})

export const fromHome = Effect.fn("SyncEnv.fromHome")(function* (home: string, platform?: HostPlatform) {
  const host = yield* Host
  if (platform === undefined && host.platform !== "darwin" && host.platform !== "linux") {
    return yield* UnsupportedPlatformError.make({ message: `unsupported platform: ${host.platform}` })
  }
  const paths = syncEnvPaths(home)
  const resolvedPlatform = platform ?? (host.platform === "darwin" ? "darwin" : "linux")
  const harnesses = yield* discoverHarnesses(home, paths.harnessesHome, resolvedPlatform)
  const rootEnv = yield* loadRootEnv(joinPath(paths.ssotHome, ".env"))
  return {
    paths,
    harnesses,
    platform: resolvedPlatform,
    rootEnv,
    installTimeoutMs: INSTALL_TIMEOUT_MS,
    harness: (id: string) => Option.getOrUndefined(Arr.findFirst(harnesses, (item) => item.id === id)),
  } satisfies SyncEnvValue
})

export class SyncEnv extends Context.Service<SyncEnv, SyncEnvValue>()("agents-sync/services/SyncEnv") {
  static readonly fromHome = fromHome
}

export const Live = Layer.effect(
  SyncEnv,
  Effect.gen(function* () {
    const host = yield* Host
    return yield* fromHome(host.home)
  }),
)
