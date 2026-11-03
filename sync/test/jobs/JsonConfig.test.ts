import { afterEach, expect, test } from "bun:test"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunFileSystem } from "@effect/platform-bun"
import { Effect, Layer } from "effect"

import { syncJsonConfig } from "#jobs/JsonConfig"
import { FilesPosix } from "#platform/Files"

const { join } = path
const live = Layer.mergeAll(FilesPosix, BunFileSystem.layer)

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})
test("preserves destination-only paths while managed values win", async () => {
  const root = mkdtempSync(join(tmpdir(), "json-config-"))
  roots.push(root)
  const src = join(root, "source")
  const dst = join(root, "dest")
  writeFileSync(src, '{ // comment\n "nested": {"managed": 1},\n}')
  writeFileSync(dst, '{"nested":{"managed":2,"local":3}}')
  await Effect.runPromise(
    syncJsonConfig(src, dst, ["nested.managed", "nested.local"]).pipe(Effect.provide(live)),
  )
  expect(readFileSync(dst, "utf8")).toBe('{\n  "nested": {\n    "managed": 1,\n    "local": 3\n  }\n}\n')
})
test("copies original JSONC verbatim when nothing is preserved", async () => {
  const root = mkdtempSync(join(tmpdir(), "json-config-"))
  roots.push(root)
  const src = join(root, "source")
  const dst = join(root, "dest")
  const text = '{ /* comment */ "x": 1, }'
  writeFileSync(src, text)
  await Effect.runPromise(syncJsonConfig(src, dst).pipe(Effect.provide(live)))
  expect(readFileSync(dst, "utf8")).toBe(text)
})
