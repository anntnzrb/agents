import { afterEach, expect, test } from "bun:test"
import {
  chmodSync,
  existsSync,
  lstatSync,
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

import { BunServices } from "@effect/platform-bun"
import { Array as Arr, Effect, Layer, Schema } from "effect"

import { syncEnvPaths } from "#domain/Harness"
import {
  WRAPPER_MARKER,
  readWrapperState,
  reconcileWrapperFiles,
  renderLaunchWrapper,
  renderManagedToolWrapper,
  wrapperDestinations,
} from "#jobs/Wrappers"
import { FilesPosix } from "#platform/Files"
import { Output } from "#services/Output"

const { join } = path
const json = Schema.fromJsonString(Schema.Unknown)
const roots: string[] = []
const fixture = () => {
  const home = mkdtempSync(join(tmpdir(), "sync-wrappers-"))
  roots.push(home)
  return { ...syncEnvPaths(home), harnesses: [] }
}
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})
const warnings: string[] = []
const output = Layer.succeed(
  Output,
  Output.of({
    write: () => Effect.void,
    err: () => Effect.void,
    warn: (message) =>
      Effect.sync(() => {
        warnings.push(message)
      }),
  }),
)
const layer = Layer.mergeAll(BunServices.layer, FilesPosix, output)

test("rendered scripts quote arguments and forward caller arguments", () => {
  const script = renderLaunchWrapper("/home/o'hare/runtime", "a'b")
  expect(script).toContain("'/home/o'\"'\"'hare/runtime/sync-current/sync'")
  expect(script).toContain("launch 'a'\"'\"'b' -- \"$@\"")
  expect(renderManagedToolWrapper("/some tool", ["--config", "a'b"])).toContain(
    "exec '/some tool' '--config' 'a'\"'\"'b' \"$@\"",
  )
  const destinations = wrapperDestinations(fixture())
  expect(Arr.map((entry: { readonly path: string }) => path.basename(entry.path))(destinations)).toEqual([
    "mcporter",
    "paseo",
    "summarize",
  ])
})

test("reconciliation owns marked files, preserves conflicts and removes only safe stale files", async () => {
  const env = fixture()
  const bin = join(env.home, ".local", "bin")
  const state = join(env.managedStateHome, "wrappers.json")
  mkdirSync(bin, { recursive: true })
  mkdirSync(env.managedStateHome, { recursive: true })
  const stale = join(bin, "stale")
  const outside = join(env.home, "outside")
  const conflict = join(bin, "user")
  const link = join(bin, "link")
  const managed = join(bin, "managed")
  writeFileSync(stale, `# ${WRAPPER_MARKER}\n`)
  writeFileSync(outside, `# ${WRAPPER_MARKER}\n`)
  writeFileSync(conflict, "user script")
  symlinkSync(outside, link)
  const initial = await Effect.runPromise(
    Schema.encodeEffect(json)({ version: 1, entries: [stale, outside] }),
  )
  writeFileSync(state, initial)
  const content = `#!/bin/sh\n# ${WRAPPER_MARKER}\nexit 0\n`
  const desired = Arr.map((target: string) => ({ path: target, content }))([managed, conflict, link])
  const result = await Effect.runPromise(reconcileWrapperFiles(env, desired).pipe(Effect.provide(layer)))
  expect(result).toEqual({
    owned: [managed],
    conflicts: [link, conflict, outside],
    removed: [stale],
  })
  expect(existsSync(stale)).toBe(false)
  expect(readFileSync(outside, "utf8")).toContain(WRAPPER_MARKER)
  expect(readFileSync(conflict, "utf8")).toBe("user script")
  expect(lstatSync(link).isSymbolicLink()).toBe(true)
  expect(statSync(managed).mode & 0o777).toBe(0o755)
  const persisted = await Effect.runPromise(Schema.decodeEffect(json)(readFileSync(state, "utf8")))
  expect(persisted).toEqual({
    version: 1,
    entries: [managed],
  })
  const inode = statSync(managed).ino
  chmodSync(managed, 0o644)
  await Effect.runPromise(reconcileWrapperFiles(env, desired).pipe(Effect.provide(layer)))
  expect(statSync(managed).ino).toBe(inode)
  expect(statSync(managed).mode & 0o777).toBe(0o755)
})

test("invalid and JSONC state is handled without trusting relative paths", async () => {
  const env = fixture()
  mkdirSync(env.managedStateHome, { recursive: true })
  const state = join(env.managedStateHome, "wrappers.json")
  writeFileSync(state, '{ // comment\n "version": 1, "entries": ["relative", "/z", "/z", "/a",], }')
  const valid = await Effect.runPromise(readWrapperState(state).pipe(Effect.provide(layer)))
  expect(valid).toEqual({ version: 1, entries: ["/a", "/z"] })
  writeFileSync(state, '{"version": 2, "entries": []}')
  warnings.length = 0
  const invalid = await Effect.runPromise(readWrapperState(state).pipe(Effect.provide(layer)))
  expect(invalid).toEqual({ version: 1, entries: [] })
  expect(warnings).toHaveLength(1)
})
