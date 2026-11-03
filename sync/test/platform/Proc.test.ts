import { describe, expect, test } from "bun:test"

import { Effect, Option, String as Str } from "effect"

import { MAX_OUTPUT_BYTES } from "#domain/Constants"
import { detailFromOutput } from "#domain/ProcessDetail"
import { Proc } from "#platform/Proc"

const run = <A, E>(program: Effect.Effect<A, E, Proc>) =>
  Effect.runPromise(program.pipe(Effect.provide(Proc.layer)))

describe("Proc", () => {
  test("captures both streams and translates failures", async () => {
    const result = await run(
      Effect.gen(function* () {
        const proc = yield* Proc
        const captured = yield* proc.run(["/bin/sh", "-c", "printf out; printf err >&2; exit 4"])
        const outcome = yield* proc.outcome(["/bin/sh", "-c", "printf problem >&2; exit 2"])
        return { captured, outcome }
      }),
    )
    expect(result.captured).toEqual({
      exitCode: 4,
      stdout: "out",
      stderr: "err",
      timedOut: false,
      outputLimited: false,
    })
    expect(result.outcome).toEqual({ _tag: "Failure", detail: "problem" })
    expect(detailFromOutput(" yes ", " ")).toBe("yes")
    expect(detailFromOutput("", "")).toBe("unknown error")
    expect(detailFromOutput(Str.repeat(2001)("a"), "")).toBe(`${Str.repeat(2000)("a")}…[truncated]`)
  })

  test("resolves commands using the supplied PATH and reports missing commands", async () => {
    const result = await run(
      Effect.gen(function* () {
        const proc = yield* Proc
        return {
          shell: yield* proc.resolveExecutable("sh", undefined, { PATH: "/bin" }),
          missing: yield* proc.run(["not-a-command"], { env: { PATH: null } }),
          outcome: yield* proc.outcome([]),
        }
      }),
    )
    expect(Option.getOrUndefined(result.shell)).toBe("/bin/sh")
    expect(result.missing.exitCode).toBe(127)
    expect(result.outcome).toEqual({ _tag: "MissingCommand" })
  })

  test("overlays and removes environment variables", async () => {
    const result = await run(
      Effect.gen(function* () {
        const proc = yield* Proc
        return yield* proc.run(["/bin/sh", "-c", `printf '%s:%s' "$SYNC_TEST" "\${HOME-unset}"`], {
          env: { SYNC_TEST: "value", HOME: null },
        })
      }),
    )
    expect(result.stdout).toBe("value:unset")
  })

  test("times out and kills descendants holding captured pipes", async () => {
    const result = await run(
      Effect.gen(function* () {
        const proc = yield* Proc
        return yield* proc.run(["/bin/sh", "-c", "printf ready; sleep 30 & wait"], { timeoutMs: 100 })
      }),
    )
    expect(result.timedOut).toBe(true)
    expect(result.stdout).toBe("ready")
  }, 5000)

  test("enforces a shared output byte cap", async () => {
    const result = await run(
      Effect.gen(function* () {
        const proc = yield* Proc
        return yield* proc.run(["/bin/sh", "-c", "yes x"], { timeoutMs: 5000 })
      }),
    )
    expect(result.outputLimited).toBe(true)
    expect(Buffer.byteLength(result.stdout) + Buffer.byteLength(result.stderr)).toBe(MAX_OUTPUT_BYTES)
  }, 10_000)
})
