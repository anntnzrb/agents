import { expect, test } from "bun:test"

import { Effect } from "effect"

import { Host, PosixLayer } from "#platform/Host"

test("host captures the process environment and exposes the clock", async () => {
  const before = Date.now()
  const result = await Effect.runPromise(
    Effect.gen(function* () {
      const host = yield* Host
      return { host, now: yield* host.now }
    }).pipe(Effect.provide(PosixLayer)),
  )
  expect(result.host.pid).toBe(process.pid)
  expect(result.host.uid).toBe(process.getuid?.() ?? -1)
  expect(result.host.platform).toBe(process.platform)
  expect(result.host.arch).toBe(process.arch)
  expect(result.host.home).toBeTruthy()
  expect(result.host.cacheHome).toBe(
    process.env["XDG_CACHE_HOME"] !== undefined && process.env["XDG_CACHE_HOME"] !== ""
      ? process.env["XDG_CACHE_HOME"]
      : `${result.host.home}/.cache`,
  )
  expect(result.host.env).toEqual(process.env)
  expect(result.host.env).not.toBe(process.env)
  expect(result.now).toBeGreaterThanOrEqual(before)
  expect(result.now).toBeLessThanOrEqual(Date.now())
})

test("host probes process liveness", async () => {
  const alive = await Effect.runPromise(
    Effect.gen(function* () {
      const host = yield* Host
      return yield* host.isPidAlive(process.pid)
    }).pipe(Effect.provide(PosixLayer)),
  )
  expect(alive).toBe(true)
})
