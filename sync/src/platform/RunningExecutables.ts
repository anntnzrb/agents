import { existsSync, readdirSync, realpathSync, readlinkSync } from "node:fs"
import path from "node:path"

import { Array as Arr, Context, Effect, Layer, Option, String as Str } from "effect"

import { RUNNING_EXECUTABLES_TIMEOUT_MS } from "#domain/Constants"
import { Proc } from "#platform/Proc"

// realpath(strict=False) retains paths that disappeared while processes were inspected.
const realPath = (pathname: string): string => {
  try {
    return realpathSync(pathname)
  } catch {
    return path.resolve(pathname)
  }
}

const linuxExecutables = Effect.sync(() => {
  if (!existsSync("/proc/self/exe")) {
    return Option.none<ReadonlySet<string>>()
  }
  const paths = new Set<string>()
  try {
    for (const entry of readdirSync("/proc")) {
      if (!/^\d+$/u.test(entry)) {
        continue
      }
      try {
        const link = `/proc/${entry}/exe`
        const target = readlinkSync(link)
        paths.add(realPath(path.resolve(`/proc/${entry}`, target)))
      } catch {
        /* Process exited or is inaccessible. */
      }
    }
    return Option.some<ReadonlySet<string>>(paths)
  } catch {
    return Option.none<ReadonlySet<string>>()
  }
})
export class RunningExecutables extends Context.Service<
  RunningExecutables,
  {
    readonly get: Effect.Effect<Option.Option<ReadonlySet<string>>>
  }
>()("agents-sync/platform/RunningExecutables") {
  static readonly layer = Layer.effect(
    RunningExecutables,
    Effect.gen(function* () {
      const proc = yield* Proc
      const get = Effect.gen(function* () {
        const linux = yield* linuxExecutables
        if (Option.isSome(linux)) {
          return linux
        }
        const result = yield* proc
          .run(["lsof", "-n", "-w", "-a", "-u", String(process.getuid?.() ?? 0), "-d", "txt", "-Fn"], {
            timeoutMs: RUNNING_EXECUTABLES_TIMEOUT_MS,
          })
          .pipe(Effect.option)
        if (
          Option.isNone(result) ||
          result.value.timedOut ||
          result.value.outputLimited ||
          result.value.stdout === ""
        ) {
          return Option.none<ReadonlySet<string>>()
        }
        return yield* Effect.sync(() => {
          const lines = Str.split(result.value.stdout, /\r?\n/u)
          const paths = Arr.filter(
            (line: unknown): line is string => typeof line === "string" && Str.startsWith("n/")(line),
          )(lines)
          const resolved = Arr.map((line: string) => realPath(Str.slice(1)(line)))(paths)
          return Option.some<ReadonlySet<string>>(new Set(resolved))
        })
      })
      return RunningExecutables.of({ get })
    }),
  )
}
