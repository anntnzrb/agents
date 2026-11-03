import { afterEach, expect, test } from "bun:test"
import {
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import nodePath from "node:path"

import { BunFileSystem } from "@effect/platform-bun"
import { Array as Arr, Effect, Layer, Option, String as Str } from "effect"
import type { FileSystem } from "effect"

import { harnessFromAdapter, harnessManagedStatePath, harnessRoot } from "#domain/Harness"
import { HARNESS_ADAPTERS } from "#domain/HarnessAdapters"
import type { SyncPlan } from "#domain/Plan"
import { FilesPosix } from "#platform/Files"
import type { Files } from "#platform/Files"
import {
  cleanManagedEntries,
  loadRecordedEntryNames,
  planManagedEntriesForSyncPlan,
  recordManagedEntries,
  writeRecordedEntryNames,
} from "#services/ManagedState"
import { Output } from "#services/Output"

const { join } = nodePath

const roots: string[] = []
const messages: string[] = []
const fixture = () => {
  const root = mkdtempSync(join(tmpdir(), "managed-state-"))
  roots.push(root)
  return root
}
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
  messages.length = 0
})
const layer = Layer.mergeAll(
  BunFileSystem.layer,
  FilesPosix,
  Layer.succeed(
    Output,
    Output.of({
      write: () => Effect.void,
      writeError: () => Effect.void,
      warn: (message) =>
        Effect.sync(() => {
          messages.push(message)
        }),
      err: (message) =>
        Effect.sync(() => {
          messages.push(message)
        }),
    }),
  ),
)
const run = <A, E>(effect: Effect.Effect<A, E, FileSystem.FileSystem | Files | Output>): Promise<A> =>
  Effect.runPromise(effect.pipe(Effect.provide(layer)))

test("loads safe unique names and recovers malformed and missing state", async () => {
  const root = fixture()
  const path = join(root, "state.json")
  expect(await run(loadRecordedEntryNames(path))).toEqual([])
  expect(messages).toEqual([])
  writeFileSync(path, '["good.txt", "..", "/tmp/escape", "nested/path", "../outside", "good.txt"]')
  expect(await run(loadRecordedEntryNames(path))).toEqual(["good.txt"])
  writeFileSync(path, "{bad")
  expect(await run(loadRecordedEntryNames(path))).toEqual([])
  writeFileSync(path, "{}")
  expect(await run(loadRecordedEntryNames(path))).toEqual([])
  writeFileSync(path, '["valid", 1]')
  expect(await run(loadRecordedEntryNames(path))).toEqual([])
  writeFileSync(path, new Uint8Array([128, 255]))
  expect(await run(loadRecordedEntryNames(path))).toEqual([])
  expect(messages).toHaveLength(4)
})

test("writes sorted state atomically, preserving identical files and replacing symlinks", async () => {
  const root = fixture()
  const path = join(root, "state", "codex.json")
  await run(writeRecordedEntryNames(path, ["beta", "alpha", "alpha"]))
  const expected = '[\n  "alpha",\n  "beta"\n]\n'
  expect(readFileSync(path, "utf8")).toBe(expected)
  const before = lstatSync(path)
  await run(writeRecordedEntryNames(path, ["alpha", "beta"]))
  expect(lstatSync(path).ino).toBe(before.ino)
  const target = join(root, "target")
  writeFileSync(target, expected)
  rmSync(path)
  symlinkSync(target, path)
  await run(writeRecordedEntryNames(path, ["alpha", "beta"]))
  expect(lstatSync(path).isSymbolicLink()).toBe(false)
  expect(readFileSync(target, "utf8")).toBe(expected)
})

test("plans and cleans active and inactive harnesses without touching current or unsafe names", async () => {
  const root = fixture()
  const managedStateHome = join(root, "state")
  mkdirSync(managedStateHome)
  const codexAdapter = Option.getOrThrow(Arr.findFirst(HARNESS_ADAPTERS, (adapter) => adapter.id === "codex"))
  const ampAdapter = Option.getOrThrow(Arr.findFirst(HARNESS_ADAPTERS, (adapter) => adapter.id === "amp"))
  const codex = harnessFromAdapter(codexAdapter, root)
  const amp = harnessFromAdapter(ampAdapter, root)
  const codexRoot = harnessRoot(codex)
  const ampRoot = harnessRoot(amp)
  mkdirSync(codexRoot, { recursive: true })
  mkdirSync(ampRoot, { recursive: true })
  for (const name of ["current", "old", "cleanup"]) {
    writeFileSync(join(codexRoot, name), name)
  }
  writeFileSync(join(ampRoot, "orphan"), "old")
  const codexState = harnessManagedStatePath(codex, managedStateHome)
  const ampState = harnessManagedStatePath(amp, managedStateHome)
  writeFileSync(codexState, '["old", "current", "../escape"]')
  writeFileSync(ampState, '["orphan"]')
  const syncPlan: Pick<SyncPlan, "harnesses"> = {
    harnesses: [
      {
        harness: codex,
        statePath: codexState,
        root: codexRoot,
        sourceRoot: "",
        instructionTarget: "",
        currentEntryNames: ["current"],
        cleanupEntryNames: ["cleanup", "../escape"],
        hooks: [],
      },
    ],
  }
  const plan = await run(
    planManagedEntriesForSyncPlan({ home: root, managedStateHome, platform: "linux" }, syncPlan),
  )
  expect(plan.harnesses).toEqual([
    {
      statePath: codexState,
      cleanupPaths: [join(codexRoot, "cleanup"), join(codexRoot, "old")],
      currentEntryNames: ["current"],
      active: true,
    },
    { statePath: ampState, cleanupPaths: [join(ampRoot, "orphan")], currentEntryNames: [], active: false },
  ])
  expect(Arr.some<string>(Str.includes("skipping unsafe"))(messages)).toBe(true)
  expect(await run(cleanManagedEntries(plan))).toBe(true)
  expect(existsSync(join(codexRoot, "current"))).toBe(true)
  expect(existsSync(join(codexRoot, "old"))).toBe(false)
  expect(existsSync(join(ampRoot, "orphan"))).toBe(false)
  expect(await run(recordManagedEntries(plan))).toBe(true)
  expect(readFileSync(codexState, "utf8")).toBe('[\n  "current"\n]\n')
  expect(existsSync(ampState)).toBe(false)
})

test("cleanup and recording report failures while continuing subsequent work", async () => {
  const root = fixture()
  const blocker = join(root, "blocker")
  writeFileSync(blocker, "file")
  const later = join(root, "later")
  writeFileSync(later, "remove")
  const plan = {
    harnesses: [
      {
        statePath: join(blocker, "state"),
        cleanupPaths: [join(blocker, "child"), later],
        currentEntryNames: [],
        active: true,
      },
      { statePath: join(root, "good.json"), cleanupPaths: [], currentEntryNames: ["good"], active: true },
    ],
  }
  expect(await run(cleanManagedEntries(plan))).toBe(false)
  expect(existsSync(later)).toBe(false)
  expect(await run(recordManagedEntries(plan))).toBe(false)
  expect(readFileSync(join(root, "good.json"), "utf8")).toContain("good")
  expect(Arr.some<string>(Str.includes("cleanup failed"))(messages)).toBe(true)
  expect(Arr.some<string>(Str.includes("managed state write failed"))(messages)).toBe(true)
})
