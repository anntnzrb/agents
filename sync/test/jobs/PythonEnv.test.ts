import { afterEach, expect, test } from "bun:test"
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunFileSystem, BunPath } from "@effect/platform-bun"
import { Effect, Layer } from "effect"

import { ensurePythonEnv } from "#jobs/PythonEnv"
import { Proc } from "#platform/Proc"
import { Output } from "#services/Output"

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})
test("python bootstrap skips an existing environment and warns if uv is missing", async () => {
  const home = mkdtempSync(path.join(tmpdir(), "python-env-"))
  roots.push(home)
  const warnings: string[] = []
  const proc = Proc.of({
    commandExists: () => Effect.succeed(false),
    resolveExecutable: () => Effect.succeedNone,
    run: () => Effect.succeed({ exitCode: 0, stdout: "", stderr: "", timedOut: false, outputLimited: false }),
    outcome: () => Effect.succeed({ _tag: "Success" }),
  })
  const output = Output.of({
    write: () => Effect.void,
    err: () => Effect.void,
    warn: (message) =>
      Effect.sync(() => {
        warnings.push(message)
      }),
  })
  const layer = Layer.mergeAll(
    BunFileSystem.layer,
    BunPath.layer,
    Layer.succeed(Proc, proc),
    Layer.succeed(Output, output),
  )
  mkdirSync(path.join(home, ".omp/python-env/bin"), { recursive: true })
  writeFileSync(path.join(home, ".omp/python-env/bin/python"), "")
  await Effect.runPromise(ensurePythonEnv(home, [".omp", "python-env"], 1000).pipe(Effect.provide(layer)))
  expect(warnings).toEqual([])
  rmSync(path.join(home, ".omp/python-env/bin/python"))
  await Effect.runPromise(ensurePythonEnv(home, [".omp", "python-env"], 1000).pipe(Effect.provide(layer)))
  expect(warnings).toEqual(["uv not found; skipping python-env bootstrap."])
})
