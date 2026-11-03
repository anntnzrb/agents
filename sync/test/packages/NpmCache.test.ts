import { afterEach, expect, test } from "bun:test"
import { chmodSync, mkdirSync, mkdtempSync, readlinkSync, rmSync, symlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunServices } from "@effect/platform-bun"
import { Array as Arr, Effect, Layer, Option } from "effect"
import type { FileSystem, Path } from "effect"

import {
  currentCachedPackage,
  npmCacheLayout,
  prepareNpmPackage,
  refreshNpmPackage,
} from "#packages/NpmCache"
import { Host } from "#platform/Host"
import type { Links } from "#platform/Links"
import { LinksPosix } from "#platform/Links"
import type { Lock } from "#platform/Lock"
import { LockPosix } from "#platform/Lock"
import { Proc } from "#platform/Proc"
import { RunningExecutables } from "#platform/RunningExecutables"
import { Output } from "#services/Output"

const dirs: string[] = []
afterEach(() => {
  for (const dir of dirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true })
  }
})
const spec = { tool: "tool", package: "@scope/tool", bin: "tool" }
const ok = { exitCode: 0, stdout: "", stderr: "", timedOut: false, outputLimited: false }

test("installs, rotates versions, and falls back to the healthy cache", async () => {
  const home = mkdtempSync(path.join(tmpdir(), "npm-cache-"))
  dirs.push(home)
  const options = { home, cacheHome: path.join(home, "cache") }
  let version = "1.0.0"
  let fail = false
  const commands: string[][] = []
  const proc = Proc.of({
    run: (args) =>
      Effect.sync(() => {
        commands.push([...args])
        if (args[1] === "view") {
          return { ...ok, exitCode: fail ? 1 : 0, stdout: version }
        }
        if (args[1] === "install") {
          const stage = args[3] ?? ""
          const binary = path.join(stage, "node_modules/.bin/tool")
          const pkg = path.join(stage, "node_modules/@scope/tool")
          mkdirSync(path.dirname(binary), { recursive: true })
          mkdirSync(pkg, { recursive: true })
          writeFileSync(binary, "#!/bin/sh\nexit 0\n")
          chmodSync(binary, 0o755)
          writeFileSync(path.join(pkg, "package.json"), `{ "name": "@scope/tool", "version": "${version}" }`)
        }
        return ok
      }),
    resolveExecutable: () => Effect.succeedNone,
    commandExists: () => Effect.succeed(true),
    outcome: () => Effect.succeed({ _tag: "Success" }),
  })
  const now = Effect.succeed(0)
  const running = RunningExecutables.of({ get: Effect.succeedSome(new Set<string>()) })
  const layer = Layer.mergeAll(
    BunServices.layer,
    LinksPosix,
    LockPosix,
    Layer.succeed(
      Host,
      Host.of({
        platform: "darwin",
        arch: "arm64",
        pid: 123,
        uid: 1,
        home,
        cacheHome: options.cacheHome,
        env: {},
        now,
        isPidAlive: () => Effect.succeed(true),
      }),
    ),
    Layer.succeed(Proc, proc),
    Layer.succeed(RunningExecutables, running),
    Layer.succeed(
      Output,
      Output.of({ write: () => Effect.void, err: () => Effect.void, warn: () => Effect.void }),
    ),
  )
  const run = <A, E>(
    effect: Effect.Effect<
      A,
      E,
      Host | Proc | RunningExecutables | Output | Lock | Links | FileSystem.FileSystem | Path.Path
    >,
  ) => Effect.runPromise(effect.pipe(Effect.provide(layer)))
  const first = await run(prepareNpmPackage(spec, options))
  expect(first.resolvedVersion).toBe("1.0.0")
  expect(readlinkSync(first.layout.currentLink)).toBe("versions/1.0.0")
  version = "2.0.0"
  expect(await run(refreshNpmPackage(spec, options))).toBe(true)
  expect(readlinkSync(first.layout.previousLink)).toBe("versions/1.0.0")
  fail = true
  const fallback = await run(prepareNpmPackage(spec, options))
  expect(fallback.resolvedVersion).toBe("2.0.0")
  const installs = Arr.filter<string[]>((cmd) => cmd[1] === "install")(commands)
  expect(installs).toHaveLength(2)
  writeFileSync(path.join(first.layout.versionsDir, "2.0.0/node_modules/@scope/tool/package.json"), "{}")
  const invalid = await run(currentCachedPackage(spec, options))
  expect(Option.isNone(invalid)).toBe(true)
})

test("cache keys distinguish packages and malformed current links are ignored", async () => {
  const home = mkdtempSync(path.join(tmpdir(), "npm-cache-"))
  dirs.push(home)
  const options = { home, cacheHome: path.join(home, "cache") }
  const layout = npmCacheLayout(spec, options)
  expect(layout.versionsDir).not.toBe(npmCacheLayout({ ...spec, package: "other" }, options).versionsDir)
  mkdirSync(path.dirname(layout.currentLink), { recursive: true })
  symlinkSync("versions/missing", layout.currentLink)
  const now = Effect.succeed(0)
  const layer = Layer.mergeAll(
    BunServices.layer,
    LinksPosix,
    Layer.succeed(
      Host,
      Host.of({
        platform: "darwin",
        arch: "arm64",
        pid: 1,
        uid: 1,
        home,
        cacheHome: options.cacheHome,
        env: {},
        now,
        isPidAlive: () => Effect.succeed(true),
      }),
    ),
  )
  const current = await Effect.runPromise(currentCachedPackage(spec, options).pipe(Effect.provide(layer)))
  expect(Option.isNone(current)).toBe(true)
})
