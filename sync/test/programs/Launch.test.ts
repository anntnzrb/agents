import { afterEach, expect, test } from "bun:test"
import { chmodSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunServices } from "@effect/platform-bun"
import { Effect, Layer } from "effect"
import { FetchHttpClient } from "effect/http"

import { supportedHarness, syncEnvPaths } from "#domain/Harness"
import { harnessPackageSpec } from "#packages/Launch"
import { npmCacheLayout } from "#packages/NpmCache"
import { Exec, ExecError } from "#platform/Exec"
import type { ExecPlan } from "#platform/Exec"
import { FilesPosix } from "#platform/Files"
import { Host } from "#platform/Host"
import { LinksPosix } from "#platform/Links"
import { LockPosix } from "#platform/Lock"
import { Proc } from "#platform/Proc"
import { RunningExecutables } from "#platform/RunningExecutables"
import { launch } from "#programs/Launch"
import { Live as HttpLayer } from "#services/Http"
import { PosixLayer as OutputLayer } from "#services/Output"
import { SyncEnv } from "#services/SyncEnv"

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})

test("launch prepends tool and harness defaults before forwarded arguments", async () => {
  const home = mkdtempSync(path.join(tmpdir(), "sync-program-launch-"))
  roots.push(home)
  const original = supportedHarness(home, "codex", "linux")
  if (original === undefined || original.launcher._tag !== "Npm") {
    throw new Error("missing codex harness")
  }
  const harness = { ...original, launcher: { ...original.launcher, defaultArgs: ["--harness-default"] } }
  const specs = [harnessPackageSpec(harness), { tool: "mcporter", package: "mcporter", bin: "mcporter" }]
  for (const spec of specs) {
    const layout = npmCacheLayout(spec, { home })
    const root = path.join(layout.versionsDir, "1.2.3")
    const bin = path.join(root, "node_modules", ".bin", spec.bin)
    mkdirSync(path.dirname(bin), { recursive: true })
    mkdirSync(path.join(root, "node_modules", spec.package), { recursive: true })
    writeFileSync(bin, "#!/bin/sh\n")
    chmodSync(bin, 0o755)
    writeFileSync(
      path.join(root, "node_modules", spec.package, "package.json"),
      `{"name":"${spec.package}","version":"1.2.3"}`,
    )
    symlinkSync("versions/1.2.3", layout.currentLink)
  }
  const plans: ExecPlan[] = []
  // Record the plan, then fail like a real exec error so launch returns instead of replacing the process.
  const recordPlan = Effect.fnUntraced(function* (plan: ExecPlan) {
    plans.push(plan)
    return yield* ExecError.make({ executable: plan.executable, message: "test", cause: null })
  })
  const host = Host.of({
    home,
    cacheHome: path.join(home, ".cache"),
    platform: "linux",
    arch: "x64",
    pid: 1,
    uid: 1,
    env: {},
    now: Effect.succeed(0),
    isPidAlive: () => Effect.succeed(false),
  })
  const hostLayer = Layer.succeed(Host, host)
  const syncEnv = SyncEnv.of({
    paths: syncEnvPaths(home),
    harnesses: [harness],
    platform: "linux",
    rootEnv: {},
    installTimeoutMs: 1000,
    harness: (id) => (id === harness.id ? harness : undefined),
  })
  const runningExecutables = RunningExecutables.layer.pipe(Layer.provide(Layer.merge(Proc.layer, hostLayer)))
  const layer = Layer.mergeAll(
    BunServices.layer,
    hostLayer,
    FilesPosix,
    FetchHttpClient.layer,
    LinksPosix,
    LockPosix,
    Proc.layer,
    runningExecutables,
    OutputLayer,
    HttpLayer,
    Layer.succeed(SyncEnv, syncEnv),
    Layer.succeed(Exec, Exec.of({ exec: recordPlan })),
  )
  await Effect.runPromise(launch("codex", ["user"]).pipe(Effect.provide(layer)))
  await Effect.runPromise(launch("mcporter", ["user"]).pipe(Effect.provide(layer)))
  expect(plans).toMatchObject([
    { args: ["--harness-default", "user"] },
    { args: ["--config", path.join(home, ".mcporter", "mcporter.json"), "user"] },
  ])
})
