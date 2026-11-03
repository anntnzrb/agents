import { afterEach, expect, test } from "bun:test"
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunFileSystem } from "@effect/platform-bun"
import { Array as Arr, Effect, Layer } from "effect"

import { PosixLayer } from "#platform/Host"
import { fromHome } from "#services/SyncEnv"

const dirs: string[] = []
afterEach(() => {
  for (const dir of dirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true })
  }
})
const home = (): string => {
  const dir = mkdtempSync(path.join(tmpdir(), "sync-env-"))
  dirs.push(dir)
  return dir
}
const layer = Layer.merge(BunFileSystem.layer, PosixLayer)

test("derives paths and treats a missing root env as empty", async () => {
  const dir = home()
  const env = await Effect.runPromise(fromHome(dir, "linux").pipe(Effect.provide(layer)))
  expect(env.paths.ssotHome).toBe(path.join(dir, "src/agents"))
  expect(env.paths.skillsHome).toBe(path.join(dir, "src/agents/skills"))
  expect(env.paths.harnessesHome).toBe(path.join(dir, "src/agents/harnesses"))
  expect(env.paths.runtimeHome).toBe(path.join(dir, ".local/share/agents"))
  expect(env.rootEnv).toEqual({})
  expect(env.harnesses).toEqual([])
  expect(env.installTimeoutMs).toBe(120_000)
})

test("loads dotenv literals and excludes empty values", async () => {
  const dir = home()
  const root = path.join(dir, "src/agents")
  mkdirSync(root, { recursive: true })
  writeFileSync(
    path.join(root, ".env"),
    `# comment\nQUOTED="secret # literal"\nSINGLE='single'\nEMPTY=\nVARIABLE=\${UNEXPANDED}\nAPI_KEY=12345\n`,
  )
  const env = await Effect.runPromise(fromHome(dir, "linux").pipe(Effect.provide(layer)))
  expect(env.rootEnv).toEqual({
    QUOTED: "secret # literal",
    SINGLE: "single",
    VARIABLE: `\${UNEXPANDED}`,
    API_KEY: "12345",
  })
})

test("discovers directories including directory links, not ordinary files", async () => {
  const dir = home()
  const root = path.join(dir, "src/agents/harnesses")
  mkdirSync(path.join(root, "codex"), { recursive: true })
  writeFileSync(path.join(root, "claude"), "not a directory")
  symlinkSync(path.join(root, "codex"), path.join(root, "amp"))
  const env = await Effect.runPromise(fromHome(dir, "linux").pipe(Effect.provide(layer)))
  const ids = Arr.map((harness: (typeof env.harnesses)[number]) => harness.id)(env.harnesses)
  expect(ids).toEqual(["codex", "amp"])
  expect(env.harness("codex")?.id).toBe("codex")
  expect(env.harness("claude")).toBeUndefined()
})

test("non-missing root env read failures are typed", async () => {
  const dir = home()
  const envPath = path.join(dir, "src/agents/.env")
  mkdirSync(envPath, { recursive: true })
  const result = await Effect.runPromise(Effect.result(fromHome(dir, "linux")).pipe(Effect.provide(layer)))
  expect(result._tag).toBe("Failure")
  if (result._tag === "Failure") {
    expect(result.failure._tag).toBe("RootEnvReadError")
    expect(result.failure.message).toBe(`failed to read root environment file ${envPath}`)
  }
})
