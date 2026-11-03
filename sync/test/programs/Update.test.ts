import { afterEach, expect, test } from "bun:test"
import { mkdtempSync, rmSync, symlinkSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunFileSystem } from "@effect/platform-bun"
import { Effect, Layer } from "effect"
import type { FileSystem } from "effect"

import { syncEnvPaths } from "#domain/Harness"
import { Host } from "#platform/Host"
import { runtimeRelease, shouldHandOff } from "#programs/Handoff"
import type { SyncEnvValue } from "#services/SyncEnv"

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})

test("handoff occurs only when an existing runtime changes and this is not a handoff", async () => {
  const root = mkdtempSync(path.join(tmpdir(), "sync-handoff-"))
  roots.push(root)
  const env: SyncEnvValue = {
    paths: { ...syncEnvPaths(root), runtimeHome: root },
    harnesses: [],
    platform: "linux",
    rootEnv: {},
    installTimeoutMs: 1000,
    harness: () => undefined,
  }
  const host = Host.of({
    platform: "linux",
    arch: "x64",
    pid: 1,
    uid: 1,
    home: root,
    cacheHome: root,
    env: {},
    now: Effect.succeed(0),
    isPidAlive: () => Effect.succeed(true),
  })
  const layer = Layer.mergeAll(BunFileSystem.layer, Layer.succeed(Host, host))
  const run = <A, E>(effect: Effect.Effect<A, E, FileSystem.FileSystem | Host>, hostLayer = layer) =>
    Effect.runPromise(effect.pipe(Effect.provide(hostLayer)))
  expect(await run(runtimeRelease(env))).toBeNull()
  symlinkSync("release-new", path.join(root, "sync-current"))
  expect(await run(runtimeRelease(env))).toBe("release-new")
  expect(await run(shouldHandOff(env, null))).toBe(false)
  expect(await run(shouldHandOff(env, "release-new"))).toBe(false)
  expect(await run(shouldHandOff(env, "release-old"))).toBe(true)
  const handedOff = Layer.mergeAll(
    BunFileSystem.layer,
    Layer.succeed(Host, Host.of({ ...host, env: { AGENTS_SYNC_HANDOFF: "1" } })),
  )
  expect(await run(shouldHandOff(env, "release-old"), handedOff)).toBe(false)
})
