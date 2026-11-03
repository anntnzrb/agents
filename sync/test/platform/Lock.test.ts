import { afterEach, expect, test } from "bun:test"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import pathModule from "node:path"

import { Effect, Option } from "effect"

import { Lock, LockPosix } from "#platform/Lock"

const dirs: string[] = []
afterEach(() => {
  for (const dir of dirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true })
  }
})

const directory = (): string => {
  const dir = mkdtempSync(pathModule.join(tmpdir(), "sync-lock-"))
  dirs.push(dir)
  return dir
}

test("sync lock writes pid, excludes another acquisition, and releases on scope exit", async () => {
  const dir = directory()
  const path = pathModule.join(dir, "state", "lock")
  await Effect.runPromise(
    Effect.gen(function* () {
      const lock = yield* Lock
      yield* Effect.scoped(
        Effect.gen(function* () {
          const stateDir = pathModule.join(dir, "state")
          const acquired = yield* lock.tryAcquireSyncLock(stateDir, path)
          expect(Option.isSome(acquired)).toBe(true)
          expect(readFileSync(path, "utf8")).toBe(`pid=${process.pid}\n`)
          const busy = yield* lock.tryAcquire(path)
          expect(Option.isNone(busy)).toBe(true)
        }),
      )
      const reacquired = yield* Effect.scoped(lock.tryAcquire(path))
      expect(Option.isSome(reacquired)).toBe(true)
    }).pipe(Effect.provide(LockPosix)),
  )
})

test("all-or-none releases earlier locks when a later lock is busy", async () => {
  const dir = directory()
  const first = pathModule.join(dir, "a")
  const second = pathModule.join(dir, "b")
  writeFileSync(first, "first")
  writeFileSync(second, "second")
  await Effect.runPromise(
    Effect.scoped(
      Effect.gen(function* () {
        const lock = yield* Lock
        const acquired = yield* lock.tryAcquire(second)
        expect(Option.isSome(acquired)).toBe(true)
        const all = yield* lock.tryAcquireAll([first, second])
        expect(Option.isNone(all)).toBe(true)
        const reacquired = yield* Effect.scoped(lock.tryAcquire(first))
        expect(Option.isSome(reacquired)).toBe(true)
        expect(readFileSync(first, "utf8")).toBe("first")
      }),
    ).pipe(Effect.provide(LockPosix)),
  )
})

test("lock failures release a partially acquired set", async () => {
  const dir = directory()
  const first = pathModule.join(dir, "a")
  writeFileSync(first, "")
  await Effect.runPromise(
    Effect.gen(function* () {
      const lock = yield* Lock
      const missing = pathModule.join(dir, "missing")
      const result = yield* Effect.result(Effect.scoped(lock.tryAcquireAll([first, missing])))
      expect(result._tag).toBe("Failure")
      const reacquired = yield* Effect.scoped(lock.tryAcquire(first))
      expect(Option.isSome(reacquired)).toBe(true)
    }).pipe(Effect.provide(LockPosix)),
  )
})

test("a successfully acquired set is held until scope exit", async () => {
  const dir = directory()
  const paths = [pathModule.join(dir, "a"), pathModule.join(dir, "b")]
  for (const path of paths) {
    writeFileSync(path, "")
  }
  await Effect.runPromise(
    Effect.gen(function* () {
      const lock = yield* Lock
      yield* Effect.scoped(
        Effect.gen(function* () {
          const acquired = yield* lock.tryAcquireAll(paths)
          expect(Option.isSome(acquired)).toBe(true)
          for (const path of paths) {
            const busy = yield* lock.tryAcquire(path)
            expect(Option.isNone(busy)).toBe(true)
          }
        }),
      )
      for (const path of paths) {
        const reacquired = yield* Effect.scoped(lock.tryAcquire(path))
        expect(Option.isSome(reacquired)).toBe(true)
      }
    }).pipe(Effect.provide(LockPosix)),
  )
})

test("failure in the scoped use releases the lock", async () => {
  const dir = directory()
  const path = pathModule.join(dir, "lock")
  writeFileSync(path, "")
  await Effect.runPromise(
    Effect.gen(function* () {
      const lock = yield* Lock
      yield* Effect.result(
        Effect.scoped(
          Effect.gen(function* () {
            yield* lock.tryAcquire(path)
            return yield* Effect.fail("failed")
          }),
        ),
      )
      const reacquired = yield* Effect.scoped(lock.tryAcquire(path))
      expect(Option.isSome(reacquired)).toBe(true)
    }).pipe(Effect.provide(LockPosix)),
  )
})
