import { dlopen, FFIType } from "bun:ffi"

import { Context, Effect, Layer, Schema } from "effect"

// The runtime ignores SIGPIPE and SIGXFSZ and sets O_NONBLOCK on shared stdio, and
// both survive execve. Restore SIG_DFL and blocking stdio so the harness behaves as
// if started from a shell. Only O_NONBLOCK differs between Darwin and Linux.
const SIGPIPE = 13
const SIGXFSZ = 25
const F_GETFL = 3
const F_SETFL = 4
const O_NONBLOCK = process.platform === "darwin" ? 0x4 : 0o4000
// fcntl is variadic but FFI calls are not: pass the argument both in the third
// register and in the first stack slot, where Darwin arm64 reads variadic arguments.
const i64 = FFIType.i64
const libc = dlopen(process.platform === "darwin" ? "/usr/lib/libSystem.B.dylib" : "libc.so.6", {
  signal: { args: [FFIType.i32, FFIType.ptr], returns: FFIType.ptr },
  fcntl: { args: [FFIType.i32, FFIType.i32, i64, i64, i64, i64, i64, i64, i64], returns: FFIType.i32 },
})
const fcntl = (fd: number, cmd: number, arg: number) => libc.symbols.fcntl(fd, cmd, arg, 0, 0, 0, 0, 0, arg)

export interface ExecPlan {
  readonly executable: string
  readonly args: readonly string[]
  readonly env: Readonly<Record<string, string>>
}

export class ExecError extends Schema.TaggedError<ExecError, { readonly brand: unique symbol }>()(
  "ExecError",
  {
    executable: Schema.String,
    message: Schema.String,
    cause: Schema.Defect(),
  },
) {}

export interface ExecService {
  readonly exec: (plan: ExecPlan) => Effect.Effect<never, ExecError>
}

export class Exec extends Context.Service<Exec, ExecService>()("agents-sync/platform/Exec") {}

export const PosixLayer = Layer.succeed(
  Exec,
  Exec.of({
    exec: Effect.fn("Exec.exec")(function* (plan: ExecPlan) {
      for (const stream of [process.stdout, process.stderr]) {
        yield* Effect.callback<undefined, ExecError>((resume) => {
          stream.write("", (cause) => {
            resume(
              cause === undefined || cause === null
                ? Effect.undefined
                : Effect.fail(
                    ExecError.make({ executable: plan.executable, message: "failed to flush output", cause }),
                  ),
            )
          })
        })
      }
      return yield* Effect.try({
        try: () => {
          if (process.execve === undefined) {
            throw new Error("process.execve is unavailable")
          }
          for (const signal of [SIGPIPE, SIGXFSZ]) {
            libc.symbols.signal(signal, null)
          }
          for (const fd of [0, 1, 2]) {
            const flags = fcntl(fd, F_GETFL, 0)
            if (flags >= 0 && (flags & O_NONBLOCK) !== 0) {
              fcntl(fd, F_SETFL, flags & ~O_NONBLOCK)
            }
          }
          return process.execve(plan.executable, [plan.executable, ...plan.args], plan.env)
        },
        catch: (cause) =>
          ExecError.make({ executable: plan.executable, message: `exec ${plan.executable} failed`, cause }),
      })
    }),
  }),
)
