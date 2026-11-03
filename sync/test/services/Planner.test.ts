import { afterEach, expect, test } from "bun:test"
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunFileSystem } from "@effect/platform-bun"
import { Array as Arr, Effect, Option, String as Str } from "effect"
import type { FileSystem } from "effect"

import { discoverHarnesses, syncEnvPaths } from "#domain/Harness"
import type { ExtensionDepsHookPlan } from "#domain/Plan"
import { buildSyncPlan, topLevelEntryNames } from "#services/Planner"
import type { SyncEnvValue } from "#services/SyncEnv"

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})
const fixture = (ids: string[], skills = false): SyncEnvValue => {
  const home = mkdtempSync(path.join(tmpdir(), "sync-planner-"))
  roots.push(home)
  const paths = syncEnvPaths(home)
  for (const id of ids) {
    mkdirSync(path.join(paths.harnessesHome, id), { recursive: true })
  }
  if (skills) {
    mkdirSync(path.join(paths.skillsHome, "current"), { recursive: true })
  }
  mkdirSync(paths.ssotHome, { recursive: true })
  writeFileSync(
    path.join(paths.ssotHome, "agents.toml"),
    '[gateway]\nbase_url = "http://localhost:8317/v1/"\n',
  )
  const harnesses = discoverHarnesses(home, ids, "linux")
  return {
    paths,
    harnesses,
    platform: "linux",
    rootEnv: {},
    installTimeoutMs: 10_000,
    harness: (id) => Option.getOrUndefined(Arr.findFirst(harnesses, (item) => item.id === id)),
  }
}
const run = <A, E>(effect: Effect.Effect<A, E, FileSystem.FileSystem>): Promise<A> =>
  Effect.runPromise(effect.pipe(Effect.provide(BunFileSystem.layer)))

test("plans runtime, managed entries, hooks and skills", async () => {
  const env = fixture(["opencode", "pi", "omp"], true)
  mkdirSync(path.join(env.paths.harnessesHome, "pi", "agent"), { recursive: true })
  writeFileSync(path.join(env.paths.harnessesHome, "pi", "agent", "z"), "")
  const plan = await run(buildSyncPlan(env))
  expect(plan.jobs[0]).toEqual({
    _tag: "SyncRuntimeInstall",
    sourceRoot: path.join(env.paths.ssotHome, "sync"),
    releasesRoot: path.join(env.paths.runtimeHome, "sync-releases"),
    currentLink: path.join(env.paths.runtimeHome, "sync-current"),
    timeoutMs: 10_000,
  })
  const extensionHooks = Arr.filter<ExtensionDepsHookPlan>((hook) =>
    Str.endsWith(".extension-deps.json")(hook.statePath),
  )(plan.hooks)
  expect(Arr.map((hook: ExtensionDepsHookPlan) => [hook.harness.id, hook.root])(extensionHooks)).toEqual([
    ["opencode", path.join(env.paths.home, ".config/opencode")],
    ["pi", path.join(env.paths.home, ".pi/agent/extensions")],
    ["omp", path.join(env.paths.home, ".omp/agent")],
  ])
  expect(
    Arr.filter<ExtensionDepsHookPlan>((hook) => Str.endsWith(".skills-deps.json")(hook.statePath))(
      plan.hooks,
    ),
  ).toHaveLength(3)
  expect(
    Option.getOrUndefined(Arr.findFirst(plan.harnesses, (item) => item.harness.id === "pi"))
      ?.currentEntryNames,
  ).toEqual(["AGENTS.md", "skills", "z"])
  expect(plan.cliProxyDeployment.gateway.base_url).toBe("http://localhost:8317/v1")
})

test("preserves devin keys and publishes only declared templates with placeholders", async () => {
  const env = fixture(["devin", "claude", "codex"])
  writeFileSync(
    path.join(env.paths.harnessesHome, "claude/settings.json"),
    `{"url":"\${CLIPROXY_CLIENT_ORIGIN}"}`,
  )
  writeFileSync(path.join(env.paths.harnessesHome, "codex/config.toml"), 'url = "ordinary"')
  const plan = await run(buildSyncPlan(env))
  expect(Option.getOrUndefined(Arr.findFirst(plan.jobs, (job) => job._tag === "PreserveJsonKeys"))).toEqual({
    _tag: "PreserveJsonKeys",
    src: path.join(env.paths.harnessesHome, "devin/config.json"),
    dst: path.join(env.paths.home, ".config/devin/config.json"),
    preservePaths: ["devin", "shell.setup_complete", "shell.startup_messages_remaining"],
  })
  const devin = Option.getOrUndefined(
    Arr.findFirst(
      plan.jobs,
      (job) => job._tag === "Dir" && job.dst === path.join(env.paths.home, ".config/devin"),
    ),
  )
  expect(devin?._tag === "Dir" && devin.preservePaths).toContain("config.json")
  const claude = Option.getOrUndefined(
    Arr.findFirst(plan.jobs, (job) => job._tag === "Dir" && job.dst === path.join(env.paths.home, ".claude")),
  )
  expect(claude?._tag === "Dir" && claude.preservePaths).toContain("settings.json")
  const publication = Option.getOrUndefined(
    Arr.findFirst(plan.jobs, (job) => job._tag === "CliProxyEndpointTemplates"),
  )
  expect(publication?._tag === "CliProxyEndpointTemplates" && publication.targets).toEqual([
    {
      src: path.join(env.paths.harnessesHome, "claude/settings.json"),
      dst: path.join(env.paths.home, ".claude/settings.json"),
      preserveTopLevels: [],
    },
  ])
  expect(plan.hooks).toEqual([])
})

test("missing directories are empty and malformed settings fail planning", async () => {
  const env = fixture([])
  const missing = path.join(env.paths.home, "missing")
  const names = await run(topLevelEntryNames(missing))
  expect(names).toEqual([])
  writeFileSync(path.join(env.paths.ssotHome, "agents.toml"), "not valid toml =")
  const result = await Effect.runPromise(
    buildSyncPlan(env).pipe(Effect.flip, Effect.provide(BunFileSystem.layer)),
  )
  expect(result._tag).toBe("PlannerError")
})
