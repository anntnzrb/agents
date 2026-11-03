import { spawn } from "node:child_process"
import type { ChildProcessByStdio } from "node:child_process"
import { accessSync, constants, statSync } from "node:fs"
import path from "node:path"
import type { Readable } from "node:stream"

import { Array as Arr, Context, Effect, Layer, Option, Record as Rec, Schema, String as Str } from "effect"

import { MAX_OUTPUT_BYTES } from "#domain/Constants"
import { detailFromOutput } from "#domain/ProcessDetail"

export const ProcessResult = Schema.Struct({
  exitCode: Schema.Finite,
  stdout: Schema.String,
  stderr: Schema.String,
  timedOut: Schema.Boolean,
  outputLimited: Schema.Boolean,
})
export type ProcessResult = typeof ProcessResult.Type
export const CommandOutcome = Schema.Union([
  Schema.TaggedStruct("Success", {}),
  Schema.TaggedStruct("MissingCommand", {}),
  Schema.TaggedStruct("Failure", { detail: Schema.String }),
  Schema.TaggedStruct("TimedOut", {}),
  Schema.TaggedStruct("OutputLimit", { detail: Schema.String }),
])
export type CommandOutcome = typeof CommandOutcome.Type
export interface RunProcessOptions {
  readonly cwd?: string | undefined
  readonly env?: Readonly<Record<string, string | null>> | undefined
  readonly timeoutMs?: number | undefined
}
export class ProcError extends Schema.TaggedError<ProcError, { readonly brand: unique symbol }>()(
  "ProcError",
  {
    command: Schema.Array(Schema.String),
    cause: Schema.Defect(),
  },
) {}

const resolve = (
  command: string,
  cwd: string | undefined,
  searchPath: string | undefined,
): Option.Option<string> => {
  const direct = Str.includes("/")(command)
  const candidates = direct
    ? [cwd !== undefined && cwd !== "" && !path.isAbsolute(command) ? path.join(cwd, command) : command]
    : Arr.map(
        Arr.filter(Str.split(searchPath ?? "", path.delimiter), (part) => part !== ""),
        (part) => path.join(part, command),
      )
  for (const candidate of candidates) {
    try {
      const stat = statSync(candidate)
      if (stat.isDirectory() || (!direct && (stat.mode & 0o111) === 0)) {
        continue
      }
      accessSync(candidate, constants.X_OK)
      return Option.some(candidate)
    } catch {
      // A missing or inaccessible candidate does not stop PATH search.
    }
  }
  return Option.none()
}

type CapturedChild = ChildProcessByStdio<null, Readable, Readable>

const killGroup = (child: CapturedChild): void => {
  try {
    if (child.pid !== undefined) {
      process.kill(-child.pid, "SIGKILL")
      return
    }
  } catch {
    // The process group may already have exited.
  }
  try {
    child.kill("SIGKILL")
  } catch {
    /* Already gone. */
  }
}

interface Captured {
  readonly child: CapturedChild
  readonly done: Promise<number>
  readonly stdout: Buffer[]
  readonly stderr: Buffer[]
  outputLimited: boolean
  finished: boolean
  discard: boolean
}

const start = (
  executable: string,
  args: readonly string[],
  options: RunProcessOptions,
  env: NodeJS.ProcessEnv,
): Captured => {
  const child = spawn(executable, args, {
    cwd: options.cwd,
    env,
    detached: true,
    stdio: ["ignore", "pipe", "pipe"],
  })
  const { promise, resolve: resolveDone, reject } = Promise.withResolvers<number>()
  child.once("error", reject)
  const captured: Captured = {
    child,
    stdout: [],
    stderr: [],
    outputLimited: false,
    finished: false,
    discard: false,
    done: promise,
  }
  child.once("close", (code, signal) => {
    captured.finished = true
    resolveDone(code ?? (signal === "SIGKILL" ? -9 : 1))
  })
  let total = 0
  const drain =
    (chunks: Buffer[]) =>
    (data: Buffer): void => {
      if (captured.outputLimited || captured.discard) {
        return
      }
      const available = MAX_OUTPUT_BYTES - total
      if (data.length > available) {
        if (available > 0) {
          chunks.push(data.subarray(0, available))
        }
        captured.outputLimited = true
        killGroup(child)
      } else {
        chunks.push(data)
        total += data.length
      }
    }
  child.stdout.on("data", drain(captured.stdout))
  child.stderr.on("data", drain(captured.stderr))
  return captured
}

const emptyResult = (): ProcessResult => ({
  exitCode: 127,
  stdout: "",
  stderr: "",
  timedOut: false,
  outputLimited: false,
})

const releaseCaptured = (resource: Captured) =>
  Effect.gen(function* () {
    if (!resource.finished) {
      killGroup(resource.child)
    }
    yield* Effect.promise(() =>
      resource.done.then(
        () => undefined,
        () => undefined,
      ),
    )
  })

const run = Effect.fn("Proc.run")(function* (command: readonly string[], options: RunProcessOptions = {}) {
  const first = command[0]
  if (first === undefined || first === "") {
    return emptyResult()
  }
  const env: NodeJS.ProcessEnv = { ...process.env }
  for (const [key, value] of Rec.toEntries(options.env ?? {})) {
    if (value === null) {
      Reflect.deleteProperty(env, key)
    } else {
      env[key] = value
    }
  }
  const executable = resolve(first, options.cwd, env["PATH"])
  if (Option.isNone(executable)) {
    return emptyResult()
  }
  return yield* Effect.scoped(
    Effect.gen(function* () {
      const captured = yield* Effect.acquireRelease(
        Effect.try({
          try: () => start(executable.value, command.slice(1), options, env),
          catch: (cause) => ProcError.make({ command, cause }),
        }),
        releaseCaptured,
      )
      const wait = Effect.tryPromise({
        try: () => captured.done,
        catch: (cause) => ProcError.make({ command, cause }),
      })
      const completed = yield* options.timeoutMs === undefined
        ? Effect.asSome(wait)
        : Effect.timeoutOption(wait, Math.max(0, options.timeoutMs))
      const timedOut = Option.isNone(completed)
      if (timedOut) {
        captured.discard = true
        killGroup(captured.child)
      }
      const exitCode = Option.isNone(completed) ? yield* wait : completed.value
      return {
        exitCode,
        stdout: Buffer.concat(captured.stdout).toString("utf8"),
        stderr: Buffer.concat(captured.stderr).toString("utf8"),
        timedOut,
        outputLimited: captured.outputLimited,
      }
    }),
  )
})

// Runs a command that shares this process's stdio and process group: output
// streams live and terminal signals reach it. Returns its exit status;
// interruption kills the child.
const runAttached = (command: readonly string[], env: Readonly<Record<string, string>>) => {
  const [executable, ...args] = command
  if (executable === undefined || executable === "") {
    return Effect.succeed(127)
  }
  return Effect.callback<number, ProcError>((resume) => {
    const child = spawn(executable, args, { env: { ...process.env, ...env }, stdio: "inherit" })
    child.once("error", (cause) => {
      resume(Effect.fail(ProcError.make({ command, cause })))
    })
    child.once("close", (code) => {
      resume(Effect.succeed(code ?? 1))
    })
    return Effect.sync(() => {
      child.kill("SIGTERM")
    })
  })
}
export class Proc extends Context.Service<
  Proc,
  {
    readonly run: (
      command: readonly string[],
      options?: RunProcessOptions,
    ) => Effect.Effect<ProcessResult, ProcError>
    readonly runAttached: (
      command: readonly string[],
      env: Readonly<Record<string, string>>,
    ) => Effect.Effect<number, ProcError>
    readonly resolveExecutable: (
      command: string,
      cwd?: string,
      env?: Readonly<Record<string, string | null>>,
    ) => Effect.Effect<Option.Option<string>>
    readonly commandExists: (command: string, cwd?: string) => Effect.Effect<boolean>
    readonly outcome: (
      command: readonly string[],
      cwd?: string,
      timeoutMs?: number,
    ) => Effect.Effect<CommandOutcome, ProcError>
  }
>()("agents-sync/platform/Proc") {
  static readonly layer = Layer.sync(Proc, () => {
    const resolveExecutable = Effect.fn("Proc.resolveExecutable")(function* (
      command: string,
      cwd?: string,
      env?: Readonly<Record<string, string | null>>,
    ) {
      return yield* Effect.sync(() =>
        resolve(command, cwd, env?.["PATH"] === null ? undefined : (env?.["PATH"] ?? process.env["PATH"])),
      )
    })
    const commandExists = Effect.fn("Proc.commandExists")(function* (command: string, cwd?: string) {
      const executable = yield* resolveExecutable(command, cwd)
      return Option.isSome(executable)
    })
    const outcome = Effect.fn("Proc.outcome")(function* (
      command: readonly string[],
      cwd?: string,
      timeoutMs?: number,
    ): Effect.fn.Return<CommandOutcome, ProcError> {
      const result = yield* run(command, {
        cwd,
        timeoutMs: timeoutMs !== undefined && timeoutMs > 0 ? timeoutMs : undefined,
      })
      if (result.outputLimited) {
        return { _tag: "OutputLimit", detail: `output limit exceeded (${MAX_OUTPUT_BYTES} bytes retained)` }
      }
      if (result.timedOut) {
        return { _tag: "TimedOut" }
      }
      if (result.exitCode === 127 && result.stdout === "" && result.stderr === "") {
        return { _tag: "MissingCommand" }
      }
      if (result.exitCode === 0) {
        return { _tag: "Success" }
      }
      return { _tag: "Failure", detail: detailFromOutput(result.stdout, result.stderr) }
    })
    return Proc.of({ run, runAttached, resolveExecutable, commandExists, outcome })
  })
}
