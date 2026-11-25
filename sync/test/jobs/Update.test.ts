import { afterEach, expect, test } from "bun:test"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunFileSystem, BunPath } from "@effect/platform-bun"
import { Array as Arr, Effect, Layer } from "effect"

import { fastForwardSsot, readSyncedCommit, recordSyncedCommit } from "#jobs/Update"
import { FilesPosix } from "#platform/Files"
import { Proc } from "#platform/Proc"
import { Output } from "#services/Output"

const roots: string[] = []
const git = (cwd: string, args: readonly string[]) => {
  const result = Bun.spawnSync(["git", ...args], { cwd })
  if (result.exitCode !== 0) {
    throw new Error(result.stderr.toString())
  }
}
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})
test("synced commit persists and invalid state is ignored", async () => {
  const root = mkdtempSync(path.join(tmpdir(), "update-state-"))
  roots.push(root)
  const layer = Layer.mergeAll(BunFileSystem.layer, BunPath.layer, FilesPosix)
  const initial = await Effect.runPromise(readSyncedCommit(root).pipe(Effect.provide(layer)))
  expect(initial).toBeNull()
  await Effect.runPromise(recordSyncedCommit(root, "abc123").pipe(Effect.provide(layer)))
  const saved = await Effect.runPromise(readSyncedCommit(root).pipe(Effect.provide(layer)))
  expect(saved).toBe("abc123")
  writeFileSync(path.join(root, "update.json"), "not json")
  const invalid = await Effect.runPromise(readSyncedCommit(root).pipe(Effect.provide(layer)))
  expect(invalid).toBeNull()
})

test("fast-forward skips a checkout with local commits missing from origin", async () => {
  const root = mkdtempSync(path.join(tmpdir(), "update-fast-forward-"))
  roots.push(root)
  git(root, ["init", "-q", "--bare", "origin.git"])
  git(root, ["init", "-q", "-b", "main", "work"])
  const work = path.join(root, "work")
  git(work, ["config", "user.name", "sync-test"])
  git(work, ["config", "user.email", "sync-test@example.com"])
  writeFileSync(path.join(work, "file.txt"), "base\n")
  git(work, ["add", "file.txt"])
  git(work, ["commit", "-q", "-m", "base"])
  git(work, ["remote", "add", "origin", path.join(root, "origin.git")])
  git(work, ["push", "-q", "-u", "origin", "main"])
  writeFileSync(path.join(work, "file.txt"), "local\n")
  git(work, ["commit", "-q", "-am", "local"])

  const warnings: string[] = []
  const output = Output.of({
    write: () => Effect.void,
    writeError: () => Effect.void,
    err: () => Effect.void,
    warn: (message) => Effect.sync(() => void warnings.push(message)),
  })
  const layer = Layer.mergeAll(
    BunFileSystem.layer,
    BunPath.layer,
    FilesPosix,
    Proc.layer,
    Layer.succeed(Output, output),
  )
  const result = await Effect.runPromise(fastForwardSsot(work).pipe(Effect.provide(layer)))

  expect(result).toBeNull()
  expect(Arr.join(warnings, "\n")).toContain("1 local, 0 upstream commits")
})
