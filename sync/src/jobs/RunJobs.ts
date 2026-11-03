import { Effect, FileSystem, Path } from "effect"

import type { Job } from "#domain/Plan"
import {
  isCliproxyTargetReady,
  publishCliproxyEndpointTemplates,
  syncCliproxyEndpointTemplate,
} from "#jobs/CliProxy"
import { syncJsonConfig } from "#jobs/JsonConfig"
import { installRuntimeRelease } from "#jobs/RuntimeRelease"
import { Files } from "#platform/Files"
import type { SourceContentCache } from "#platform/Files"
import { Output } from "#services/Output"

const detail = (error: unknown): string => {
  if (typeof error === "object" && error !== null && "cause" in error && error.cause instanceof Error) {
    return error.cause.message
  }
  return error instanceof Error ? error.message : String(error)
}

type CopyJob = Extract<Job, { readonly _tag: "Dir" | "File" | "PreserveJsonKeys" }>

const runCopyJob = Effect.fn("RunJobs.runCopyJob")(function* (
  job: CopyJob,
  preservePathsByDst: ReadonlyMap<string, readonly string[]>,
  cache: SourceContentCache,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const files = yield* Files
  const output = yield* Output
  if (job._tag === "Dir") {
    const exists = yield* fs.exists(job.src)
    const info = exists ? yield* fs.stat(job.src) : undefined
    if (info?.type !== "Directory") {
      yield* output.err(`missing directory: ${job.src}`)
      return true
    }
    const preserve = [...(preservePathsByDst.get(job.dst) ?? []), ...job.preservePaths]
    yield* fs.makeDirectory(job.scope === "Children" ? job.dst : path.dirname(job.dst), { recursive: true })
    yield* job.scope === "Children"
      ? files.syncManagedChildren(job.src, job.dst, preserve, cache)
      : files.syncManagedTree(job.src, job.dst, preserve, cache)
    return true
  }
  const exists = yield* fs.exists(job.src)
  if (!exists && (job._tag !== "File" || !(yield* files.isSymlink(job.src)))) {
    yield* output.err(`missing source: ${job.src}`)
    return true
  }
  if (job._tag === "PreserveJsonKeys") {
    yield* syncJsonConfig(job.src, job.dst, job.preservePaths)
  } else if (job.endpointTemplate) {
    if (job.deployment === null) {
      yield* output.err(`missing deployment for endpoint template: ${job.src}`)
      return false
    }
    yield* syncCliproxyEndpointTemplate(job.src, job.dst, job.deployment)
  } else {
    yield* files.syncManagedTree(job.src, job.dst, [], cache)
  }
  return true
})

const runJob = Effect.fn("RunJobs.runJob")(function* (
  job: Job,
  preservePathsByDst: ReadonlyMap<string, readonly string[]>,
  cache: SourceContentCache,
  state: { readiness: boolean | undefined },
) {
  const output = yield* Output
  switch (job._tag) {
    case "Dir":
    case "File":
    case "PreserveJsonKeys": {
      return yield* runCopyJob(job, preservePathsByDst, cache)
    }
    case "CliProxyReadiness": {
      state.readiness = yield* isCliproxyTargetReady(job.deployment)
      if (!state.readiness) {
        yield* output.warn("CLIProxyAPI endpoint is not ready; preserving existing client artifacts")
      }
      return true
    }
    case "CliProxyEndpointTemplates": {
      if (state.readiness === false) {
        return true
      }
      const publication = yield* publishCliproxyEndpointTemplates(job.targets, job.deployment, {
        skipReadiness: state.readiness === true,
      })
      if (publication === "skipped" && job.targets.length > 0) {
        yield* output.warn("CLIProxyAPI endpoint is not ready; preserving existing harness endpoints")
      }
      return true
    }
    case "SyncRuntimeInstall": {
      yield* installRuntimeRelease(job)
      return true
    }
    default: {
      const exhaustive: never = job
      return exhaustive
    }
  }
})

export const runJobsWithPreserve = Effect.fn("RunJobs.runJobsWithPreserve")(function* (
  jobs: readonly Job[],
  preservePathsByDst: ReadonlyMap<string, readonly string[]> = new Map(),
) {
  const output = yield* Output
  const cache: SourceContentCache = new Map()
  const state: { readiness: boolean | undefined } = { readiness: undefined }
  for (const job of jobs) {
    const result = yield* runJob(job, preservePathsByDst, cache, state).pipe(
      Effect.catch((error) =>
        Effect.gen(function* () {
          const message =
            job._tag === "Dir" || job._tag === "File" || job._tag === "PreserveJsonKeys"
              ? `copy failed: ${job.src} -> ${job.dst} (${detail(error)})`
              : `unexpected error in ${job._tag}: ${detail(error)}`
          yield* output.err(message)
          return false
        }),
      ),
    )
    if (!result) {
      return false
    }
  }
  return true
})
