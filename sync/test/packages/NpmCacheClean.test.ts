import { afterEach, expect, test } from "bun:test"
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunFileSystem } from "@effect/platform-bun"
import { Array as Arr, Effect, Layer } from "effect"

import { cleanNpmCache } from "#packages/NpmCacheClean"
import { Host } from "#platform/Host"
import { Lock, LockPosix } from "#platform/Lock"
import { Proc } from "#platform/Proc"
import { Output } from "#services/Output"

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})

test("clean skips a busy launcher and runs after its lock is released", async () => {
  const root = mkdtempSync(path.join(tmpdir(), "npm-clean-"))
  roots.push(root)
  mkdirSync(path.join(root, ".npm", "_cacache"), { recursive: true })
  const lockPath = path.join(root, "npm-tools", "a", "lock")
  mkdirSync(path.dirname(lockPath), { recursive: true })
  writeFileSync(lockPath, "")
  const mutableCalls: string[][] = []
  const lines: string[] = []
  const host = Host.of({
    platform: "darwin",
    arch: "arm64",
    pid: 1,
    uid: 1,
    home: root,
    cacheHome: root,
    env: {},
    now: Effect.succeed(0),
    isPidAlive: () => Effect.succeed(true),
  })
  const layer = Layer.mergeAll(
    BunFileSystem.layer,
    LockPosix,
    Layer.succeed(Host, host),
    Layer.succeed(
      Output,
      Output.of({
        write: (s) =>
          Effect.sync(() => {
            lines.push(s)
          }),
        writeError: () => Effect.void,
        err: () => Effect.void,
        warn: () => Effect.void,
      }),
    ),
    Layer.succeed(
      Proc,
      Proc.of({
        commandExists: () => Effect.succeed(true),
        resolveExecutable: () => Effect.succeedSome("npm"),
        runAttached: () => Effect.succeed(0),
        run: (command) =>
          Effect.sync(() => {
            mutableCalls.push([...command])
            return { exitCode: 0, stdout: "", stderr: "", timedOut: false, outputLimited: false }
          }),
        outcome: () => Effect.succeed({ _tag: "Success" as const }),
      }),
    ),
  )
  await Effect.runPromise(
    Effect.gen(function* () {
      const lock = yield* Lock
      yield* Effect.scoped(
        Effect.gen(function* () {
          yield* lock.tryAcquire(lockPath)
          const busy = yield* cleanNpmCache()
          expect(busy).toBe(0)
          expect(mutableCalls).toEqual([])
        }),
      )
      const result = yield* cleanNpmCache()
      expect(result).toBe(0)
    }).pipe(Effect.provide(layer)),
  )
  expect(mutableCalls).toEqual([["npm", "cache", "clean", "--force"]])
  expect(Arr.join(lines, "")).toContain("a launcher holds an npm-tools lock")
})
