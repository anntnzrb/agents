import { afterEach, expect, test } from "bun:test"
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunFileSystem, BunPath } from "@effect/platform-bun"
import { Effect, Layer, String as Str } from "effect"

import { installRuntimeRelease, pruneUnreferencedReleases } from "#jobs/RuntimeRelease"
import { FilesPosix } from "#platform/Files"
import { PosixLayer } from "#platform/Host"
import { LinksPosix } from "#platform/Links"
import { Proc } from "#platform/Proc"
import { PosixLayer as OutputLive } from "#services/Output"

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})
const layer = Layer.mergeAll(
  BunFileSystem.layer,
  BunPath.layer,
  FilesPosix,
  PosixLayer,
  LinksPosix,
  Proc.layer,
  OutputLive,
)
const fixture = () => {
  const root = mkdtempSync(path.join(tmpdir(), "runtime-release-"))
  roots.push(root)
  const sourceRoot = path.join(root, "source")
  mkdirSync(path.join(sourceRoot, "src"), { recursive: true })
  writeFileSync(path.join(sourceRoot, "src", "main.ts"), 'console.log("runtime")\n')
  writeFileSync(path.join(sourceRoot, "bun.lock"), readFileSync(new URL("../../bun.lock", import.meta.url)))
  writeFileSync(
    path.join(sourceRoot, "package.json"),
    readFileSync(new URL("../../package.json", import.meta.url)),
  )
  return {
    _tag: "SyncRuntimeInstall" as const,
    sourceRoot,
    releasesRoot: path.join(root, "releases"),
    currentLink: path.join(root, "current"),
    timeoutMs: 60_000,
  }
}

test("installs a compiled release, reuses it, and publishes changed sources atomically", async () => {
  const job = fixture()
  await Effect.runPromise(installRuntimeRelease(job).pipe(Effect.provide(layer)))
  const first = realpathSync(job.currentLink)
  expect(existsSync(path.join(first, "sync"))).toBe(true)
  expect(readFileSync(path.join(first, ".release-complete"), "utf8")).toBe(`${path.basename(first)}\n`)
  expect(new Set(readdirSync(first))).toEqual(new Set([".release-complete", "sync"]))
  await Effect.runPromise(installRuntimeRelease(job).pipe(Effect.provide(layer)))
  expect(realpathSync(job.currentLink)).toBe(first)
  writeFileSync(path.join(job.sourceRoot, "src", "main.ts"), 'console.log("changed")\n')
  await Effect.runPromise(installRuntimeRelease(job).pipe(Effect.provide(layer)))
  expect(realpathSync(job.currentLink)).not.toBe(first)
  expect(existsSync(first)).toBe(true)
  await Effect.runPromise(
    pruneUnreferencedReleases(job.releasesRoot, job.currentLink, 60_000).pipe(Effect.provide(layer)),
  )
  expect(existsSync(first)).toBe(false)
})

test("failure leaves current intact and removes staging directory", async () => {
  const job = fixture()
  mkdirSync(job.releasesRoot)
  const previous = path.join(job.releasesRoot, "previous")
  mkdirSync(previous)
  symlinkSync(previous, job.currentLink)
  writeFileSync(path.join(job.sourceRoot, "src", "main.ts"), "this is not valid TypeScript !!!")
  const result = await Effect.runPromise(
    Effect.result(installRuntimeRelease(job)).pipe(Effect.provide(layer)),
  )
  expect(result._tag).toBe("Failure")
  expect(realpathSync(job.currentLink)).toBe(realpathSync(previous))
  expect(readdirSync(job.releasesRoot)).toEqual(["previous"])
})

test("pruning preserves incomplete and foreign directories, and reclaims dead stages", async () => {
  const job = fixture()
  mkdirSync(job.releasesRoot)
  const current = path.join(job.releasesRoot, Str.repeat(64)("a"))
  const old = path.join(job.releasesRoot, Str.repeat(64)("b"))
  const incomplete = path.join(job.releasesRoot, Str.repeat(64)("c"))
  const stage = path.join(job.releasesRoot, ".stage-99999999-dead")
  for (const dir of [current, old, incomplete, stage]) {
    mkdirSync(dir)
  }
  for (const dir of [current, old]) {
    writeFileSync(path.join(dir, "sync"), "binary")
    writeFileSync(path.join(dir, ".release-complete"), "complete\n")
  }
  symlinkSync(current, job.currentLink)
  await Effect.runPromise(
    pruneUnreferencedReleases(job.releasesRoot, job.currentLink, 60_000).pipe(Effect.provide(layer)),
  )
  expect(existsSync(current)).toBe(true)
  expect(existsSync(old)).toBe(false)
  expect(existsSync(incomplete)).toBe(true)
  expect(existsSync(stage)).toBe(false)
})
