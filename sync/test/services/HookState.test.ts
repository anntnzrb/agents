import { afterEach, expect, test } from "bun:test"
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunFileSystem } from "@effect/platform-bun"
import { Array as Arr, Effect, Layer, Path } from "effect"
import type { FileSystem } from "effect"

import { harnessFromAdapter } from "#domain/Harness"
import { HARNESS_ADAPTERS } from "#domain/HarnessAdapters"
import type { ExtensionDepsHookPlan } from "#domain/Plan"
import { FilesPosix } from "#platform/Files"
import type { Files } from "#platform/Files"
import {
  clearExtensionHookState,
  findGeneratedExtensionEntries,
  fingerprintTree,
  loadExtensionHookState,
  prepareExtensionHookState,
  recordExtensionHookState,
} from "#services/HookState"
import { PosixLayer } from "#services/Output"
import type { Output } from "#services/Output"

const roots: string[] = []
const fixture = () => {
  const root = mkdtempSync(path.join(tmpdir(), "sync-hook-state-"))
  roots.push(root)
  return root
}
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})
const layer = Layer.mergeAll(BunFileSystem.layer, Path.layer, FilesPosix, PosixLayer)
const run = <A, E>(effect: Effect.Effect<A, E, FileSystem.FileSystem | Path.Path | Files | Output>) =>
  Effect.runPromise(effect.pipe(Effect.provide(layer)))
const hookFor = (root: string): ExtensionDepsHookPlan => ({
  _tag: "ExtensionDeps",
  harness: harnessFromAdapter(
    HARNESS_ADAPTERS[0] ??
      (() => {
        throw new Error("missing adapter")
      })(),
    root,
  ),
  jobRoot: root,
  root: path.join(root, "home"),
  sourceRoot: path.join(root, "source"),
  relativeRoot: "extensions",
  statePath: path.join(root, "state.json"),
  timeoutMs: 1000,
})

test("fingerprints missing, stable, ignored and changed trees", async () => {
  const root = fixture()
  const missing = path.join(root, "missing")
  expect(await run(fingerprintTree(missing))).toBe(
    "ffa63583dfa6706b87d284b86b0d693a161e4840aad2c5cf6b5d27c3b9621f7d",
  )
  mkdirSync(path.join(root, "dir"))
  writeFileSync(path.join(root, "dir", "a"), "one")
  const initial = await run(fingerprintTree(root))
  mkdirSync(path.join(root, "node_modules"))
  writeFileSync(path.join(root, ".hidden"), "ignored")
  expect(await run(fingerprintTree(root))).toBe(initial)
  writeFileSync(path.join(root, "dir", "a"), "two")
  expect(await run(fingerprintTree(root))).not.toBe(initial)
})

test("fingerprints file and broken symlinks but refuses directory symlinks", async () => {
  const root = fixture()
  const source = path.join(root, "source")
  mkdirSync(source)
  writeFileSync(path.join(root, "target"), "one")
  symlinkSync(path.join(root, "target"), path.join(source, "link"))
  symlinkSync(path.join(root, "absent"), path.join(source, "broken"))
  const initial = await run(fingerprintTree(source))
  writeFileSync(path.join(root, "target"), "two")
  expect(await run(fingerprintTree(source))).not.toBe(initial)
  symlinkSync(root, path.join(source, "directory"))
  expect(await run(fingerprintTree(source)).catch(String)).toContain("refusing source directory symlink")
})

test("records and prepares generated entries, preserving mode and nested paths", async () => {
  const root = fixture()
  const hook = hookFor(root)
  mkdirSync(hook.sourceRoot)
  mkdirSync(path.join(hook.root, "skill", "node_modules"), { recursive: true })
  writeFileSync(path.join(hook.root, "package.json"), "{}")
  writeFileSync(path.join(hook.root, "skill", "bun.lock"), "")
  mkdirSync(path.join(hook.root, ".hidden"))
  writeFileSync(path.join(hook.root, ".hidden", "bun.lock"), "")
  writeFileSync(hook.statePath, "old")
  chmodSync(hook.statePath, 0o640)
  const prepared = await run(prepareExtensionHookState(hook, "known"))
  expect(prepared.shouldSkip).toBe(false)
  await run(recordExtensionHookState(hook, prepared))
  expect(statSync(hook.statePath).mode & 0o777).toBe(0o640)
  const payload = readFileSync(hook.statePath, "utf8")
  expect(payload).toBe(
    '{\n  "fingerprint": "known",\n  "generatedEntries": [\n    "package.json",\n    "skill/node_modules",\n    "skill/bun.lock"\n  ]\n}\n',
  )
  const next = await run(prepareExtensionHookState(hook, "known"))
  expect(next.shouldSkip).toBe(true)
  expect(next.preservePaths).toEqual([
    "extensions/package.json",
    "extensions/skill/bun.lock",
    "extensions/skill/node_modules",
  ])
  rmSync(path.join(hook.root, "package.json"))
  const stale = await run(prepareExtensionHookState(hook, "known"))
  expect(stale.shouldSkip).toBe(false)
  expect(stale.preservePaths).toEqual([])
  const changed = await run(prepareExtensionHookState(hook, "changed"))
  expect(changed.generatedEntries).toEqual([])
  await run(clearExtensionHookState(hook.statePath))
  await run(clearExtensionHookState(hook.statePath))
  expect(await run(loadExtensionHookState(hook.statePath))).toBeNull()
})

test("loads JSONC, filters stale state entries, and ignores malformed state", async () => {
  const root = fixture()
  const hook = hookFor(root)
  mkdirSync(hook.root)
  writeFileSync(path.join(hook.root, "package.json"), "{}")
  writeFileSync(
    hook.statePath,
    '// comment\n{"fingerprint":"fp","generatedEntries":["package.json","custom.txt","package.json",],}',
  )
  const prepared = await run(prepareExtensionHookState({ ...hook, relativeRoot: "" }, "fp"))
  expect(prepared.shouldSkip).toBe(true)
  expect(prepared.shouldRefreshState).toBe(true)
  expect(prepared.preservePaths).toEqual(["package.json"])
  const invalid = ["invalid", "[]", '{"fingerprint":1,"generatedEntries":[]}', Buffer.from([255])]
  const results = await Promise.all(
    Arr.map((contents: string | Buffer, index: number) => {
      const statePath = path.join(root, `invalid-${index}`)
      writeFileSync(statePath, contents)
      return run(loadExtensionHookState(statePath))
    })(invalid),
  )
  expect(results).toEqual([null, null, null, null])
})

test("generated discovery includes broken symlinks and does not descend into symlink directories", async () => {
  const root = fixture()
  mkdirSync(path.join(root, "child"))
  symlinkSync(path.join(root, "missing"), path.join(root, "package.json"))
  writeFileSync(path.join(root, "child", "bun.lockb"), "")
  symlinkSync(path.join(root, "child"), path.join(root, "linked"))
  expect(await run(findGeneratedExtensionEntries(root))).toEqual(["package.json", "child/bun.lockb"])
})
