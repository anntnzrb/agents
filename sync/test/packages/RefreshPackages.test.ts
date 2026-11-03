import { afterEach, expect, test } from "bun:test"
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunServices } from "@effect/platform-bun"
import { Array as Arr, Effect, Layer, Option, String as Str } from "effect"

import { harnessFromAdapter, syncEnvPaths } from "#domain/Harness"
import type { Harness } from "#domain/Harness"
import { HARNESS_ADAPTERS } from "#domain/HarnessAdapters"
import { refreshPackages } from "#packages/RefreshPackages"
import { Host } from "#platform/Host"
import { LinksPosix } from "#platform/Links"
import { Lock } from "#platform/Lock"
import { Proc } from "#platform/Proc"
import { RunningExecutables } from "#platform/RunningExecutables"
import { Http } from "#services/Http"
import { Output } from "#services/Output"
import { SyncEnv } from "#services/SyncEnv"

const dirs: string[] = []
afterEach(() => {
  for (const dir of dirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true })
  }
})

const fixture = () => {
  const home = mkdtempSync(path.join(tmpdir(), "refresh-packages-"))
  dirs.push(home)
  const warnings: string[] = []
  const attempted: string[] = []
  const busy = new Set<string>()
  const harnesses: Harness[] = []
  for (const adapter of HARNESS_ADAPTERS) {
    if (adapter.id === "codex") {
      harnesses.push(harnessFromAdapter(adapter, home))
    }
  }
  const env = {
    paths: syncEnvPaths(home),
    harnesses,
    platform: "linux" as const,
    rootEnv: {},
    installTimeoutMs: 1234,
    harness: (id: string) => Option.getOrUndefined(Arr.findFirst(harnesses, (harness) => harness.id === id)),
  }
  const output = Output.of({
    write: () => Effect.void,
    writeError: () => Effect.void,
    err: () => Effect.void,
    warn: (message) =>
      Effect.sync(() => {
        warnings.push(message)
      }),
  })
  const running = RunningExecutables.of({ get: Effect.succeedNone })
  const now = Effect.succeed(0)
  const layer = Layer.mergeAll(
    BunServices.layer,
    LinksPosix,
    Layer.succeed(SyncEnv, SyncEnv.of(env)),
    Layer.succeed(Output, output),
    Layer.succeed(
      Host,
      Host.of({
        platform: "linux",
        arch: "x64",
        pid: 1,
        uid: 1,
        home,
        cacheHome: `${home}/.cache`,
        env: {},
        now,
        isPidAlive: () => Effect.succeed(false),
      }),
    ),
    Layer.succeed(
      Lock,
      Lock.of({
        tryAcquire: () => Effect.succeedSome(undefined),
        tryAcquireAll: () => Effect.succeedSome(undefined),
        tryAcquireSyncLock: (dir) =>
          Effect.succeed(busy.has(path.basename(dir)) ? Option.none() : Option.some(undefined)),
      }),
    ),
    Layer.succeed(
      Proc,
      Proc.of({
        runAttached: () => Effect.succeed(0),
        run: (command) =>
          Effect.sync(() => {
            attempted.push(command[2] ?? "")
            return { exitCode: 1, stdout: "", stderr: "offline", timedOut: false, outputLimited: false }
          }),
        resolveExecutable: () => Effect.succeedNone,
        commandExists: () => Effect.succeed(false),
        outcome: () => Effect.succeed({ _tag: "MissingCommand" as const }),
      }),
    ),
    Layer.succeed(RunningExecutables, running),
    Layer.succeed(Http, Http.of({ getOk: () => Effect.die("unexpected HTTP") })),
  )
  return {
    home,
    warnings,
    attempted,
    busy,
    run: () => Effect.runPromise(refreshPackages().pipe(Effect.provide(layer))),
  }
}

test("continues after each failed package and fails only when the entire round fails", async () => {
  const f = fixture()
  expect(await f.run()).toBe(1)
  expect(f.attempted).toEqual([
    "mcporter@latest",
    "@getpaseo/cli@latest",
    "@steipete/summarize@latest",
    "@openai/codex@latest",
  ])
  expect(f.warnings).toHaveLength(4)
  expect(f.warnings[3]).toContain("refresh-packages: codex:")
})

test("a busy package makes a partially failed round successful", async () => {
  const f = fixture()
  f.busy.add("mcporter")
  expect(await f.run()).toBe(0)
  expect(f.attempted).not.toContain("mcporter@latest")
  expect(f.attempted).toHaveLength(3)
})

test("discovers managed wrappers without their source and ignores symlink wrappers", async () => {
  const f = fixture()
  const bin = path.join(f.home, ".local", "bin")
  mkdirSync(bin, { recursive: true })
  writeFileSync(path.join(bin, "amp"), "#!/bin/sh\n# agents-managed-wrapper:v1\n")
  symlinkSync(path.join(bin, "amp"), path.join(bin, "claude"))
  expect(await f.run()).toBe(1)
  expect(Arr.some<string>((warning) => Str.includes("refresh-packages: amp:")(warning))(f.warnings)).toBe(
    true,
  )
  expect(Arr.some<string>((warning) => Str.includes("refresh-packages: claude:")(warning))(f.warnings)).toBe(
    false,
  )
})
