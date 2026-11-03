import { expect, test } from "bun:test"

import { Effect, Layer, Option } from "effect"

import { Proc } from "#platform/Proc"
import { RunningExecutables } from "#platform/RunningExecutables"

test("detects the current process executable when the platform can inspect it", async () => {
  const layer = RunningExecutables.layer.pipe(Layer.provide(Proc.layer))
  const program = Effect.gen(function* () {
    const running = yield* RunningExecutables
    return yield* running.get
  })
  const result = await Effect.runPromise(program.pipe(Effect.provide(layer)))
  if (Option.isSome(result)) {
    expect(result.value.size).toBeGreaterThan(0)
  }
})
