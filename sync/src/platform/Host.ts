import { homedir } from "node:os"
import path from "node:path"

import { Context, Effect, Layer, String as Str } from "effect"

export interface HostService {
  readonly platform: string
  readonly arch: string
  readonly pid: number
  readonly uid: number
  readonly home: string
  readonly cacheHome: string
  readonly env: Readonly<Record<string, string | undefined>>
  readonly now: Effect.Effect<number>
  readonly isPidAlive: (pid: number) => Effect.Effect<boolean>
}

export class Host extends Context.Service<Host, HostService>()("agents-sync/platform/Host") {}

export const PosixLayer = Layer.sync(Host, () => {
  const env = { ...process.env }
  if (process.platform !== "darwin" && process.platform !== "linux") {
    throw new Error(`unsupported platform: ${process.platform}`)
  }
  const configuredHome = Str.trim(env["HOME"] ?? "")
  const home = configuredHome === "" ? homedir() : configuredHome
  return Host.of({
    platform: process.platform,
    arch: process.arch,
    pid: process.pid,
    uid: process.getuid?.() ?? -1,
    home,
    cacheHome:
      env["XDG_CACHE_HOME"] !== undefined && env["XDG_CACHE_HOME"] !== ""
        ? env["XDG_CACHE_HOME"]
        : path.join(home, ".cache"),
    env,
    isPidAlive: (pid) =>
      Effect.sync(() => {
        try {
          process.kill(pid, 0)
          return true
        } catch (error) {
          return !(typeof error === "object" && error !== null && "code" in error && error.code === "ESRCH")
        }
      }),
    now: Effect.sync(() => Date.now()),
  })
})
