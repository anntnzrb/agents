import { expect, test } from "bun:test"

import { Effect, Schema } from "effect"

import {
  HookState,
  ManagedEntries,
  WrapperState,
  normalizeHookState,
  normalizeManagedEntries,
  normalizeWrapperState,
  prepareHookState,
} from "#domain/State"

test("managed state rejects invalid payloads and filters unsafe names", () => {
  const parse = Schema.decodeUnknownEffect(ManagedEntries)
  const decode = (input: unknown) => Effect.runSync(parse(input))
  expect(normalizeManagedEntries(decode(["z", "..", "x/y", String.raw`x\y`, "", "a", "z"]))).toEqual([
    "a",
    "z",
  ])
  expect(() => decode(["ok", 1])).toThrow()
})

test("hook state keeps generated names and decides whether cache survives", () => {
  const parse = Schema.decodeUnknownEffect(HookState)
  const decode = (input: unknown) => Effect.runSync(parse(input))
  const state = normalizeHookState(
    decode({ fingerprint: "abc", generatedEntries: ["x/bun.lock", "bad", "node_modules", "node_modules"] }),
  )
  expect(state).toEqual({
    fingerprint: "abc",
    generatedEntries: ["node_modules", "x/bun.lock"],
    shouldRefreshState: true,
  })
  expect(prepareHookState("abc", state, "extensions", () => true)).toEqual({
    fingerprint: "abc",
    generatedEntries: ["node_modules", "x/bun.lock"],
    preservePaths: ["extensions/node_modules", "extensions/x/bun.lock"],
    shouldSkip: true,
    shouldRefreshState: true,
  })
  expect(prepareHookState("abc", state, "", (name) => name === "node_modules").shouldSkip).toBe(false)
  expect(prepareHookState("changed", state, "", () => true).generatedEntries).toEqual([])
  expect(() => decode({ fingerprint: "abc", generatedEntries: [42] })).toThrow()
})

test("wrapper state requires version, defaults entries and keeps absolute unique paths", () => {
  const parse = Schema.decodeUnknownEffect(WrapperState)
  const decode = (input: unknown) => Effect.runSync(parse(input))
  expect(decode({ version: 1 })).toEqual({ version: 1, entries: [] })
  expect(normalizeWrapperState(decode({ version: 1, entries: ["/b", "relative", "/a", "/b"] }))).toEqual({
    version: 1,
    entries: ["/a", "/b"],
  })
  expect(() => decode({ entries: [] })).toThrow()
  expect(() => decode({ version: 2, entries: [] })).toThrow()
})
