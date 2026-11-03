import { Array as Arr, Duration, Effect, FileSystem, Schema } from "effect"
import { HttpClient, HttpClientRequest } from "effect/http"

import {
  appendPreservedSections,
  cliproxyModelsUrl,
  extractPreservedTopLevels,
  renderCliproxyEndpointTemplate,
} from "#domain/AgentsSettings"
import type { AgentsSettings } from "#domain/AgentsSettings"
import { isObjDict } from "#domain/Jsonc"
import type { CliProxyEndpointTarget } from "#domain/Plan"
import { Files } from "#platform/Files"

export class CliProxyError extends Schema.TaggedError<CliProxyError, { readonly brand: unique symbol }>()(
  "CliProxyError",
  { message: Schema.String, cause: Schema.Defect() },
) {}

export const isCliproxyTargetReady = Effect.fn("CliProxy.isCliproxyTargetReady")(function* (
  deployment: AgentsSettings,
  timeoutMs?: number,
) {
  const client = yield* HttpClient.HttpClient
  const request = HttpClientRequest.get(cliproxyModelsUrl(deployment)).pipe(
    HttpClientRequest.setHeaders({ Accept: "application/json", "Cache-Control": "no-cache" }),
  )
  return yield* Effect.gen(function* () {
    const response = yield* client.execute(request)
    if (response.status < 200 || response.status >= 300) {
      return false
    }
    const payload: unknown = yield* response.json
    return isObjDict(payload) && Arr.isArray(payload["data"]) && payload["data"].length > 0
  }).pipe(
    Effect.timeoutOrElse({
      duration: Duration.millis(timeoutMs ?? 500),
      orElse: () => Effect.succeed(false),
    }),
    Effect.orElseSucceed(() => false),
  )
})

export const syncCliproxyEndpointTemplate = Effect.fn("CliProxy.syncCliproxyEndpointTemplate")(function* (
  src: string,
  dst: string,
  deployment: AgentsSettings,
  preserveTopLevels: readonly string[] = [],
) {
  const fs = yield* FileSystem.FileSystem
  const files = yield* Files
  const template = yield* fs.readFileString(src)
  const sourceInfo = yield* fs.stat(src)
  const destInfo = yield* fs.lstat(dst).pipe(
    Effect.catchIf(
      (error) => error.reason._tag === "NotFound",
      () => Effect.succeed(null),
    ),
  )
  const mode = destInfo?.type === "File" ? destInfo.mode & 0o777 : sourceInfo.mode & 0o777
  let preserved = ""
  if (preserveTopLevels.length > 0) {
    const existing = yield* fs.readFileString(dst).pipe(
      Effect.catchIf(
        (error) => error.reason._tag === "NotFound",
        () => Effect.succeed(""),
      ),
    )
    preserved = extractPreservedTopLevels(existing, preserveTopLevels)
  }
  const rendered = yield* Effect.try({
    try: () => renderCliproxyEndpointTemplate(template, deployment),
    catch: (cause) =>
      CliProxyError.make({ message: `render CLIProxyAPI endpoint template ${src} -> ${dst}`, cause }),
  })
  yield* files.syncTextFile(dst, appendPreservedSections(rendered, preserved), mode)
})

type Snapshot =
  | { readonly kind: "missing" | "other"; readonly path: string }
  | { readonly kind: "file"; readonly path: string; readonly content: string; readonly mode: number }
  | { readonly kind: "link"; readonly path: string; readonly target: string }

const snapshot = Effect.fn("CliProxy.snapshot")(function* (path: string) {
  const fs = yield* FileSystem.FileSystem
  const info = yield* fs.lstat(path).pipe(
    Effect.catchIf(
      (error) => error.reason._tag === "NotFound",
      () => Effect.succeed(null),
    ),
  )
  if (info === null) {
    return { kind: "missing", path } as const
  }
  if (info.type === "SymbolicLink") {
    const target = yield* fs.readLink(path)
    return { kind: "link", path, target } as const
  }
  if (info.type === "File") {
    const content = yield* fs.readFileString(path)
    return { kind: "file", path, content, mode: info.mode & 0o777 } as const
  }
  return { kind: "other", path } as const
})

const restore = Effect.fn("CliProxy.restore")(function* (snapshots: readonly Snapshot[]) {
  const fs = yield* FileSystem.FileSystem
  const files = yield* Files
  for (const item of snapshots) {
    switch (item.kind) {
      case "missing": {
        yield* files.rmEntry(item.path).pipe(Effect.ignore)
        break
      }
      case "file": {
        yield* files.syncTextFile(item.path, item.content, item.mode)
        break
      }
      case "link": {
        yield* files.rmEntry(item.path).pipe(Effect.ignore)
        yield* fs.symlink(item.target, item.path)
        break
      }
      case "other": {
        break
      }
    }
  }
})

export interface CliProxyEndpointSyncOptions {
  readonly skipReadiness?: boolean
  readonly timeoutMs?: number
}

export const publishCliproxyEndpointTemplates = Effect.fn("CliProxy.publishCliproxyEndpointTemplates")(
  function* (
    targets: readonly CliProxyEndpointTarget[],
    deployment: AgentsSettings,
    options: CliProxyEndpointSyncOptions = {},
  ) {
    if (targets.length === 0) {
      return "published" as const
    }
    if (options.skipReadiness !== true && !(yield* isCliproxyTargetReady(deployment, options.timeoutMs))) {
      return "skipped" as const
    }
    const snapshots: Snapshot[] = []
    for (const target of targets) {
      const saved = yield* snapshot(target.dst)
      snapshots.push(saved)
    }
    yield* Effect.gen(function* () {
      for (const target of targets) {
        yield* syncCliproxyEndpointTemplate(target.src, target.dst, deployment, target.preserveTopLevels)
      }
    }).pipe(Effect.onError(() => restore(snapshots).pipe(Effect.ignore)))
    return "published" as const
  },
)
