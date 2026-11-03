import { afterEach, expect, test } from "bun:test"
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunFileSystem, BunPath } from "@effect/platform-bun"
import { Effect, Layer } from "effect"

import { iterExtensionPackages } from "#jobs/ExtensionDeps"

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})

test("extension package discovery ignores hidden directories and node_modules", async () => {
  const root = mkdtempSync(path.join(tmpdir(), "extension-deps-"))
  roots.push(root)
  for (const dir of ["a", "z/nested", ".hidden", "node_modules/pkg"]) {
    mkdirSync(path.join(root, dir), { recursive: true })
    writeFileSync(path.join(root, dir, "package.json"), "{}")
  }
  const layer = Layer.merge(BunFileSystem.layer, BunPath.layer)
  const result = await Effect.runPromise(iterExtensionPackages(root).pipe(Effect.provide(layer)))
  expect(result).toEqual([path.join(root, "a"), path.join(root, "z/nested")])
})
