import { afterEach, expect, test } from "bun:test"
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunFileSystem, BunPath } from "@effect/platform-bun"
import { Effect, Layer, Option } from "effect"

import { installInferredImportPackages, iterExtensionPackages } from "#jobs/ExtensionDeps"
import { Proc } from "#platform/Proc"
import { Output } from "#services/Output"

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})

test("extension package discovery ignores hidden directories and node_modules", async () => {
  const root = mkdtempSync(path.join(tmpdir(), "extension-deps-"))
  roots.push(root)
  for (const dir of ["a", "z/nested", ".hidden", "node_modules/pkg"]) {
    mkdirSync(path.join(root, dir), { recursive: true })
    writeFileSync(path.join(root, dir, "package.json"), "{}")
  }
  const layer = Layer.merge(BunFileSystem.layer, BunPath.layer)
  const result = await Effect.runPromise(iterExtensionPackages(root).pipe(Effect.provide(layer)))
  expect(result).toEqual([path.join(root, "a"), path.join(root, "z/nested")])
})

test("inferred dependencies install into the extension target even when the source has stale dependencies", async () => {
  const root = mkdtempSync(path.join(tmpdir(), "extension-deps-install-"))
  roots.push(root)
  const source = path.join(root, "source")
  const target = path.join(root, "target")
  mkdirSync(path.join(source, "node_modules", "chalk"), { recursive: true })
  mkdirSync(target, { recursive: true })
  writeFileSync(path.join(source, "index.ts"), 'import chalk from "chalk"\nvoid chalk\n')

  const calls: { readonly command: readonly string[]; readonly cwd: string | undefined }[] = []
  const proc = Proc.of({
    run: () => Effect.succeed({ exitCode: 0, stdout: "", stderr: "", timedOut: false, outputLimited: false }),
    runAttached: () => Effect.succeed(0),
    resolveExecutable: (command) => Effect.succeed(command === "bun" ? Option.some("bun") : Option.none()),
    commandExists: () => Effect.succeed(true),
    outcome: (command, cwd) =>
      Effect.sync(() => {
        calls.push({ command: [...command], cwd })
        return { _tag: "Success" as const }
      }),
  })
  const output = Output.of({
    write: () => Effect.void,
    writeError: () => Effect.void,
    err: () => Effect.void,
    warn: () => Effect.void,
  })
  const layer = Layer.mergeAll(
    BunFileSystem.layer,
    BunPath.layer,
    Layer.succeed(Proc, proc),
    Layer.succeed(Output, output),
  )
  const installed = await Effect.runPromise(
    installInferredImportPackages(target, 1000, source).pipe(Effect.provide(layer)),
  )

  expect(installed).toBe(true)
  expect(calls).toEqual([{ command: ["bun", "add", "--no-save", "chalk"], cwd: target }])
})
