import { afterEach, expect, test } from "bun:test"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunFileSystem, BunPath } from "@effect/platform-bun"
import { Effect, Layer } from "effect"

import { readSyncedCommit, recordSyncedCommit } from "#jobs/Update"
import { FilesPosix } from "#platform/Files"

const roots: string[] = []
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
