import { dlopen, FFIType, read } from "bun:ffi"
import { closeSync, constants, fsyncSync, ftruncateSync, mkdirSync, openSync, writeSync } from "node:fs"

import { Array as Arr, Context, Effect, Layer, Option, Order, Schema } from "effect"
import type { Scope } from "effect"

export class LockError extends Schema.TaggedError<LockError, { readonly brand: unique symbol }>()(
  "LockError",
  {
    path: Schema.String,
    operation: Schema.String,
    cause: Schema.Defect(),
  },
) {}

export class Lock extends Context.Service<
  Lock,
  {
    readonly tryAcquire: (path: string) => Effect.Effect<Option.Option<void>, LockError, Scope.Scope>
    readonly tryAcquireSyncLock: (
      stateDir: string,
      path: string,
    ) => Effect.Effect<Option.Option<void>, LockError, Scope.Scope>
    readonly tryAcquireAll: (
      paths: readonly string[],
    ) => Effect.Effect<Option.Option<void>, LockError, Scope.Scope>
  }
>()("agents-sync/platform/Lock") {}

const library = process.platform === "darwin" ? "/usr/lib/libSystem.B.dylib" : "libc.so.6"
const libc = dlopen(library, {
  flock: { args: [FFIType.i32, FFIType.i32], returns: FFIType.i32 },
})
const errnoPointer =
  process.platform === "darwin"
    ? dlopen(library, { __error: { args: [], returns: FFIType.ptr } }).symbols.__error
    : dlopen(library, { __errno_location: { args: [], returns: FFIType.ptr } }).symbols.__errno_location

const close = (fd: number): void => {
  try {
    closeSync(fd)
  } catch {
    /* Closing is best-effort, as in the Python implementation. */
  }
}

const acquire = (path: string, create: boolean, writePid: boolean): Option.Option<number> => {
  const fd = openSync(path, constants.O_RDWR | (create ? constants.O_CREAT : 0), 0o644)
  try {
    if (libc.symbols.flock(fd, 2 | 4) !== 0) {
      const pointer = errnoPointer()
      if (pointer === null) {
        throw new Error("unable to read flock errno")
      }
      const code = read.i32(pointer, 0)
      if (code === 11 || code === 35) {
        close(fd)
        return Option.none()
      }
      throw new Error(`flock failed (errno ${code})`)
    }
    if (writePid) {
      ftruncateSync(fd, 0)
      writeSync(fd, `pid=${process.pid}\n`, 0, "utf8")
      fsyncSync(fd)
    }
    return Option.some(fd)
  } catch (error) {
    close(fd)
    throw error
  }
}

const scopedAcquire = (path: string, create: boolean, writePid: boolean) =>
  Effect.acquireRelease(
    Effect.try({
      try: () => acquire(path, create, writePid),
      catch: (cause) => LockError.make({ path, operation: "acquire", cause }),
    }),
    (result) =>
      Effect.sync(() => {
        if (Option.isSome(result)) {
          close(result.value)
        }
      }),
  )

const tryAcquire = Effect.fn("Lock.tryAcquire")(function* (path: string) {
  const result = yield* scopedAcquire(path, false, false)
  return Option.isSome(result) ? Option.some(undefined) : Option.none()
})

const tryAcquireSyncLock = Effect.fn("Lock.tryAcquireSyncLock")(function* (stateDir: string, path: string) {
  yield* Effect.try({
    try: () => mkdirSync(stateDir, { recursive: true }),
    catch: (cause) => LockError.make({ path: stateDir, operation: "mkdir", cause }),
  })
  const result = yield* scopedAcquire(path, true, true)
  return Option.isSome(result) ? Option.some(undefined) : Option.none()
})

const tryAcquireAll = Effect.fn("Lock.tryAcquireAll")(function* (paths: readonly string[]) {
  const result = yield* Effect.acquireRelease(
    Effect.try({
      try: () => {
        const held: number[] = []
        try {
          for (const path of Arr.sort(paths, Order.String)) {
            const lock = acquire(path, false, false)
            if (Option.isNone(lock)) {
              for (const fd of held) {
                close(fd)
              }
              return Option.none<number[]>()
            }
            held.push(lock.value)
          }
          return Option.some(held)
        } catch (error) {
          for (const fd of held) {
            close(fd)
          }
          throw error
        }
      },
      catch: (cause) => LockError.make({ path: Arr.join(paths, ", "), operation: "acquire all", cause }),
    }),
    (locks) =>
      Effect.sync(() => {
        if (Option.isSome(locks)) {
          for (const fd of locks.value) {
            close(fd)
          }
        }
      }),
  )
  return Option.isSome(result) ? Option.some(undefined) : Option.none()
})

export const LockPosix = Layer.succeed(Lock, Lock.of({ tryAcquire, tryAcquireSyncLock, tryAcquireAll }))
