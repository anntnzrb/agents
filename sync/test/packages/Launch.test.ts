import { afterEach, expect, test } from "bun:test"
import { chmodSync, mkdirSync, mkdtempSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunServices } from "@effect/platform-bun"
import { Effect, Layer } from "effect"

import { supportedHarness } from "#domain/Harness"
import { harnessHasCache, harnessPackageSpec, launchHarness, launchNpmPackage } from "#packages/Launch"
import { npmCacheLayout } from "#packages/NpmCache"
import { Host } from "#platform/Host"
import { LinksPosix } from "#platform/Links"
import { LockPosix } from "#platform/Lock"
import { Proc } from "#platform/Proc"
import { RunningExecutables } from "#platform/RunningExecutables"
import { Live as HttpLayer } from "#services/Http"
import { PosixLayer as OutputLayer } from "#services/Output"

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})

const setup = () => {
  const home = mkdtempSync(path.join(tmpdir(), "sync-launch-"))
  roots.push(home)
  const host = Host.of({
    home,
    cacheHome: path.join(home, "cache"),
    platform: "linux",
    arch: "x64",
    pid: 1,
    uid: 1,
    env: { PATH: "/parent/bin", SHARED: "parent", ADAPTER: "parent", UNSET: undefined },
    now: Effect.succeed(0),
    isPidAlive: () => Effect.succeed(false),
  })
  const hostLayer = Layer.succeed(Host, host)
  const runningLayer = RunningExecutables.layer.pipe(Layer.provide(Layer.mergeAll(Proc.layer, hostLayer)))
  const layer = Layer.mergeAll(
    BunServices.layer,
    hostLayer,
    LinksPosix,
    LockPosix,
    Proc.layer,
    runningLayer,
    OutputLayer,
    HttpLayer,
  )
  return {
    home,
    host,
    layer,
    env: { home, rootEnv: { ROOT: "root", SHARED: "root", ADAPTER: "root" }, installTimeoutMs: 1000 },
  }
}

const harness = (home: string, name: string) => {
  const result = supportedHarness(home, name, "linux")
  if (result === undefined) {
    throw new Error(`missing harness ${name}`)
  }
  return result
}

test("cached npm launch forwards args and merges root, parent, and adapter env", async () => {
  const { home, host, layer, env } = setup()
  const original = harness(home, "codex")
  if (original.launcher._tag !== "Npm") {
    throw new Error("expected npm")
  }
  const tool = { ...original, launcher: { ...original.launcher, env: { ADAPTER: "adapter" } } }
  const spec = harnessPackageSpec(tool)
  const layout = npmCacheLayout(spec, { home, cacheHome: host.cacheHome })
  const root = path.join(layout.versionsDir, "1.2.3")
  const bin = path.join(root, "node_modules/.bin/codex")
  mkdirSync(path.dirname(bin), { recursive: true })
  mkdirSync(path.join(root, "node_modules/@openai/codex"), { recursive: true })
  writeFileSync(bin, "#!/bin/sh\nexit 0\n")
  chmodSync(bin, 0o755)
  writeFileSync(
    path.join(root, "node_modules/@openai/codex/package.json"),
    '{"name":"@openai/codex","version":"1.2.3"}',
  )
  symlinkSync(path.join("versions", "1.2.3"), layout.currentLink)

  const plan = await Effect.runPromise(
    launchHarness(env, tool, ["--help", "hello"]).pipe(Effect.provide(layer)),
  )
  expect(plan).toEqual({
    executable: path.join(layout.currentLink, "node_modules/.bin/codex"),
    args: ["--help", "hello"],
    env: { PATH: "/parent/bin", SHARED: "parent", ROOT: "root", ADAPTER: "adapter" },
  })
  const cached = await Effect.runPromise(harnessHasCache(home, tool).pipe(Effect.provide(layer)))
  expect(cached).toBe(true)
})

test("cached static launch resolves executable and adapter env without network", async () => {
  const { home, layer, env } = setup()
  const tool = harness(home, "devin")
  const versions = path.join(home, ".local/share/devin/cli/_versions")
  const bin = path.join(versions, "9.9.9/bin/devin")
  mkdirSync(path.dirname(bin), { recursive: true })
  writeFileSync(bin, "#!/bin/sh\nexit 0\n")
  chmodSync(bin, 0o755)
  symlinkSync("9.9.9", path.join(versions, "current"))

  const plan = await Effect.runPromise(launchHarness(env, tool, ["--help"]).pipe(Effect.provide(layer)))
  expect(plan.executable).toBe(realpathSync(bin))
  expect(plan.args).toEqual(["--help"])
  expect(plan.env).toEqual({
    PATH: "/parent/bin",
    SHARED: "parent",
    ROOT: "root",
    ADAPTER: "parent",
    DEVIN_PERMISSION_MODE: "bypass",
  })
  const cached = await Effect.runPromise(harnessHasCache(home, tool).pipe(Effect.provide(layer)))
  expect(cached).toBe(true)
  expect(() => harnessPackageSpec(tool)).toThrow("static release has no npm specification")
})

test("invalid uncached npm specification reports preparation failure", async () => {
  const { layer, env } = setup()
  const result = await Effect.runPromise(
    launchNpmPackage(env, { tool: "../bad", package: "pkg", bin: "pkg" }, []).pipe(
      Effect.flip,
      Effect.provide(layer),
    ),
  )
  expect(result._tag).toBe("NpmCacheError")
})
