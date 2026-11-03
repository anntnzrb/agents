import { expect, test } from "bun:test"
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunFileSystem } from "@effect/platform-bun"
import { Effect, Layer, Path } from "effect"

import { harnessFromAdapter } from "#domain/Harness"
import { HARNESS_ADAPTERS } from "#domain/HarnessAdapters"
import type { ExtensionDepsHookPlan } from "#domain/Plan"
import { FilesPosix } from "#platform/Files"
import { prepareExtensionHookStates, preservePathsByDst } from "#programs/RunSync"
import { PosixLayer as OutputLive } from "#services/Output"

const layer = Layer.mergeAll(BunFileSystem.layer, Path.layer, FilesPosix, OutputLive)

test("prepared hook state preserves generated entries only when the fingerprint matches", async () => {
  const root = mkdtempSync(path.join(tmpdir(), "sync-hook-program-"))
  try {
    const adapter = HARNESS_ADAPTERS[0]
    if (adapter === undefined) {
      throw new Error("missing adapter")
    }
    const source = path.join(root, "source")
    const target = path.join(root, "target")
    mkdirSync(source)
    mkdirSync(target)
    writeFileSync(path.join(source, "index.ts"), "export {}")
    const hook: ExtensionDepsHookPlan = {
      _tag: "ExtensionDeps",
      harness: harnessFromAdapter(adapter, root),
      jobRoot: root,
      root: target,
      sourceRoot: source,
      relativeRoot: "extensions",
      statePath: path.join(root, "state.json"),
      timeoutMs: 1000,
    }
    const initial = await Effect.runPromise(prepareExtensionHookStates([hook]).pipe(Effect.provide(layer)))
    const prepared = initial.get(hook.statePath)
    expect(prepared?.state.shouldSkip).toBe(false)
    mkdirSync(path.join(target, "node_modules"))
    writeFileSync(
      hook.statePath,
      `{"fingerprint":"${prepared?.state.fingerprint ?? ""}","generatedEntries":["node_modules"]}`,
    )
    const matching = await Effect.runPromise(prepareExtensionHookStates([hook]).pipe(Effect.provide(layer)))
    expect(preservePathsByDst(matching).get(root)).toEqual(["extensions/node_modules"])
    writeFileSync(path.join(source, "index.ts"), "export const changed = true")
    const changed = await Effect.runPromise(prepareExtensionHookStates([hook]).pipe(Effect.provide(layer)))
    expect(preservePathsByDst(changed).size).toBe(0)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})
