import { Array as Arr, Effect, FileSystem, Order, Record as Rec, Schema } from "effect"

import {
  AGENTS_SETTINGS_FILE,
  hasCliproxyEndpointPlaceholder,
  parseAgentsSettings,
} from "#domain/AgentsSettings"
import type { AgentsSettings } from "#domain/AgentsSettings"
import {
  harnessInstructionTarget,
  harnessManagedStatePath,
  harnessRoot,
  harnessSourceRoot,
  SKILLS_DST_DIR,
  SKILLS_SOURCE_SUBDIR,
  SOURCE_AGENT_FILE,
} from "#domain/Harness"
import type { Harness } from "#domain/Harness"
import { joinPath } from "#domain/PathText"
import type { CliProxyEndpointTarget, ExtensionDepsHookPlan, HarnessPlan, Job, SyncPlan } from "#domain/Plan"
import type { SyncEnvValue } from "#services/SyncEnv"

export class PlannerError extends Schema.TaggedError<PlannerError, { readonly brand: unique symbol }>()(
  "PlannerError",
  { message: Schema.String, cause: Schema.Defect() },
) {}

export const topLevelEntryNames = Effect.fn("Planner.topLevelEntryNames")(function* (root: string) {
  const fs = yield* FileSystem.FileSystem
  const info = yield* fs.stat(root).pipe(Effect.orElseSucceed(() => null))
  if (info?.type !== "Directory") {
    return []
  }
  const entries = yield* fs
    .readDirectory(root)
    .pipe(
      Effect.mapError((cause) => PlannerError.make({ message: `read ${root} (${cause.message})`, cause })),
    )
  return Arr.sort([...new Set(entries)], Order.String)
})
const skillHook = (env: SyncEnvValue, harness: Harness, root: string): ExtensionDepsHookPlan => ({
  _tag: "ExtensionDeps",
  harness,
  jobRoot: joinPath(root, SKILLS_DST_DIR),
  root: joinPath(root, SKILLS_DST_DIR),
  sourceRoot: joinPath(env.paths.skillsHome, SKILLS_SOURCE_SUBDIR),
  relativeRoot: "",
  statePath: joinPath(env.paths.managedStateHome, `${harness.sourceName}.skills-deps.json`),
  timeoutMs: env.installTimeoutMs,
})

const buildHarnessPlans = Effect.fn("Planner.buildHarnessPlans")(function* (
  env: SyncEnvValue,
  hasSkills: boolean,
) {
  const paths = env.paths
  const harnesses: HarnessPlan[] = []
  for (const harness of env.harnesses) {
    const root = harnessRoot(harness)
    const sourceRoot = harnessSourceRoot(harness, paths.harnessesHome)
    const names = yield* topLevelEntryNames(sourceRoot)
    const currentEntryNames = Arr.sort(
      [...new Set([harness.instructionFile, ...names, ...(hasSkills ? [SKILLS_DST_DIR] : [])])],
      Order.String,
    )
    const hooks: ExtensionDepsHookPlan[] = Arr.map(
      (hook: Harness["hooks"][number]): ExtensionDepsHookPlan => ({
        _tag: "ExtensionDeps",
        harness,
        jobRoot: root,
        root: joinPath(root, hook.rootDir),
        sourceRoot: joinPath(sourceRoot, hook.rootDir),
        relativeRoot: hook.rootDir === "." ? "" : hook.rootDir,
        statePath: joinPath(paths.managedStateHome, `${harness.sourceName}.extension-deps.json`),
        timeoutMs: env.installTimeoutMs,
      }),
    )(harness.hooks)
    if (hasSkills) {
      hooks.push(skillHook(env, harness, root))
    }
    harnesses.push({
      harness,
      root,
      sourceRoot,
      instructionTarget: harnessInstructionTarget(harness),
      statePath: harnessManagedStatePath(harness, paths.managedStateHome),
      currentEntryNames,
      cleanupEntryNames: currentEntryNames,
      hooks,
    })
  }
  return harnesses
})

const readTemplates = Effect.fn("Planner.readTemplates")(function* (harnesses: readonly HarnessPlan[]) {
  const fs = yield* FileSystem.FileSystem
  const templates = new Map<Harness, string[]>()
  for (const plan of harnesses) {
    const found: string[] = []
    for (const candidate of plan.harness.cliproxyTemplates) {
      const source = joinPath(plan.sourceRoot, candidate)
      const info = yield* fs.stat(source).pipe(Effect.orElseSucceed(() => null))
      if (info?.type === "File") {
        const contents = yield* fs
          .readFileString(source)
          .pipe(
            Effect.mapError((cause) =>
              PlannerError.make({ message: `read ${source} (${cause.message})`, cause }),
            ),
          )
        if (hasCliproxyEndpointPlaceholder(contents)) {
          found.push(candidate)
        }
      }
    }
    templates.set(plan.harness, found)
  }
  return templates
})

const makeJobs = (
  env: SyncEnvValue,
  harnesses: readonly HarnessPlan[],
  templates: Map<Harness, string[]>,
  deployment: AgentsSettings,
): Job[] => {
  const paths = env.paths
  const skillsSource = joinPath(paths.skillsHome, SKILLS_SOURCE_SUBDIR)
  return [
    {
      _tag: "SyncRuntimeInstall",
      sourceRoot: joinPath(paths.ssotHome, "sync"),
      releasesRoot: joinPath(paths.runtimeHome, "sync-releases"),
      currentLink: joinPath(paths.runtimeHome, "sync-current"),
      timeoutMs: env.installTimeoutMs,
    },
    ...Arr.map((plan: HarnessPlan): Job => ({
      _tag: "Dir",
      src: plan.sourceRoot,
      dst: plan.root,
      scope: "Children",
      preservePaths: [...(templates.get(plan.harness) ?? []), ...Rec.keys(plan.harness.preserveJsonKeys)],
    }))(harnesses),
    ...Arr.flatMap((plan: HarnessPlan): Job[] =>
      Arr.map(([rel, preservePaths]: [string, readonly string[]]): Job => ({
        _tag: "PreserveJsonKeys",
        src: joinPath(plan.sourceRoot, rel),
        dst: joinPath(plan.root, rel),
        preservePaths,
      }))(Rec.toEntries(plan.harness.preserveJsonKeys)),
    )(harnesses),
    ...Arr.map((plan: HarnessPlan): Job => ({
      _tag: "Dir",
      src: skillsSource,
      dst: joinPath(plan.root, SKILLS_DST_DIR),
      scope: "Tree",
      preservePaths: [],
    }))(harnesses),
    ...Arr.map((plan: HarnessPlan): Job => ({
      _tag: "File",
      src: joinPath(paths.ssotHome, SOURCE_AGENT_FILE),
      dst: plan.instructionTarget,
      endpointTemplate: false,
      deployment: null,
    }))(harnesses),
    ...configJobs(env, harnesses, templates, deployment),
  ]
}

const configJobs = (
  env: SyncEnvValue,
  harnesses: readonly HarnessPlan[],
  templates: Map<Harness, string[]>,
  deployment: AgentsSettings,
): Job[] => {
  const paths = env.paths
  const settingsPath = joinPath(paths.ssotHome, AGENTS_SETTINGS_FILE)
  const targets: CliProxyEndpointTarget[] = Arr.flatMap((plan: HarnessPlan) =>
    Arr.map((rel: string) => ({
      src: joinPath(plan.sourceRoot, rel),
      dst: joinPath(plan.root, rel),
      preserveTopLevels: plan.harness.cliproxyPreserveTopLevels[rel] ?? [],
    }))(templates.get(plan.harness) ?? []),
  )(harnesses)
  return [
    { _tag: "CliProxyReadiness", deployment },
    {
      _tag: "File",
      src: settingsPath,
      dst: joinPath(paths.runtimeHome, AGENTS_SETTINGS_FILE),
      endpointTemplate: false,
      deployment: null,
    },
    {
      _tag: "File",
      src: joinPath(paths.ssotHome, "tools", "mcporter", "mcporter.jsonc"),
      dst: joinPath(paths.mcporterHome, "mcporter.json"),
      endpointTemplate: false,
      deployment: null,
    },
    {
      _tag: "File",
      src: joinPath(paths.ssotHome, "tools", "summarize", "config.json"),
      dst: joinPath(paths.summarizeHome, "config.json"),
      endpointTemplate: true,
      deployment,
    },
    { _tag: "CliProxyEndpointTemplates", targets, deployment },
  ]
}

export const buildSyncPlan = Effect.fn("Planner.buildSyncPlan")(function* (env: SyncEnvValue) {
  const fs = yield* FileSystem.FileSystem
  const skillsSource = joinPath(env.paths.skillsHome, SKILLS_SOURCE_SUBDIR)
  const skillsInfo = yield* fs.stat(skillsSource).pipe(Effect.orElseSucceed(() => null))
  const harnesses = yield* buildHarnessPlans(env, skillsInfo?.type === "Directory")
  const settingsPath = joinPath(env.paths.ssotHome, AGENTS_SETTINGS_FILE)
  const text = yield* fs
    .readFileString(settingsPath)
    .pipe(
      Effect.mapError((cause) =>
        PlannerError.make({ message: `read agents settings ${settingsPath} (${cause.message})`, cause }),
      ),
    )
  const deployment = yield* Effect.try({
    try: () => parseAgentsSettings(Bun.TOML.parse(text)),
    catch: (cause) =>
      PlannerError.make({ message: `parse agents settings ${settingsPath} (${String(cause)})`, cause }),
  })
  const templates = yield* readTemplates(harnesses)
  const jobs = makeJobs(env, harnesses, templates, deployment)
  return {
    harnesses,
    jobs,
    hooks: Arr.flatMap((plan: HarnessPlan) => plan.hooks)(harnesses),
    cliProxyDeployment: deployment,
  } satisfies SyncPlan
})
