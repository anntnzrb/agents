import { Schema } from "effect"

import {
  DEFAULT_INSTRUCTION_FILE,
  ExtensionDepsHook,
  HARNESS_ADAPTERS,
  HarnessId,
  StaticRelease,
} from "#domain/HarnessAdapters"
import type { HarnessAdapter, HostPlatform } from "#domain/HarnessAdapters"
import { joinPath } from "#domain/PathText"

export const SOURCE_AGENT_FILE = "HARNESS.md"
export const INSTALL_TIMEOUT_MS = 120_000
export const MANAGED_STATE_SUBDIR = ".local/share/agents/sync-managed"
export const SKILLS_DST_DIR = "skills"
export const SKILLS_SOURCE_SUBDIR = "current"
export const PATH_COMPONENT_PATTERN = /^[A-Za-z0-9._-]+$/u

const StringMap = Schema.Record(Schema.String, Schema.String)
const StringArrayMap = Schema.Record(Schema.String, Schema.Array(Schema.String))
export const NpmLauncher = Schema.TaggedStruct("Npm", {
  package: Schema.String,
  bin: Schema.String,
  defaultArgs: Schema.Array(Schema.String),
  env: Schema.NullOr(StringMap),
})
export type NpmLauncher = typeof NpmLauncher.Type
export const StaticReleaseLauncher = Schema.TaggedStruct("StaticRelease", {
  bin: Schema.String,
  release: StaticRelease,
  defaultArgs: Schema.Array(Schema.String),
  env: Schema.NullOr(StringMap),
})
export type StaticReleaseLauncher = typeof StaticReleaseLauncher.Type
export const HarnessLauncher = Schema.Union([NpmLauncher, StaticReleaseLauncher])
export type HarnessLauncher = typeof HarnessLauncher.Type
export const Harness = Schema.Struct({
  id: HarnessId,
  sourceName: Schema.String,
  home: Schema.String,
  launcher: HarnessLauncher,
  instructionFile: Schema.String,
  runtimeSubdir: Schema.NullOr(Schema.String),
  preserveJsonKeys: StringArrayMap,
  cliproxyTemplates: Schema.Array(Schema.String),
  cliproxyPreserveTopLevels: StringArrayMap,
  pythonEnvSegments: Schema.NullOr(Schema.Array(Schema.String)),
  hooks: Schema.Array(ExtensionDepsHook),
})
export type Harness = typeof Harness.Type

export const SyncEnvPaths = Schema.Struct({
  home: Schema.String,
  ssotHome: Schema.String,
  runtimeHome: Schema.String,
  skillsHome: Schema.String,
  harnessesHome: Schema.String,
  mcporterHome: Schema.String,
  summarizeHome: Schema.String,
  managedStateHome: Schema.String,
})
export type SyncEnvPaths = typeof SyncEnvPaths.Type

export const syncEnvPaths = (home: string): SyncEnvPaths => {
  const ssotHome = joinPath(home, "src", "agents")
  return {
    home,
    ssotHome,
    runtimeHome: joinPath(home, ".local", "share", "agents"),
    skillsHome: joinPath(ssotHome, "skills"),
    harnessesHome: joinPath(ssotHome, "harnesses"),
    mcporterHome: joinPath(home, ".mcporter"),
    summarizeHome: joinPath(home, ".summarize"),
    managedStateHome: joinPath(home, MANAGED_STATE_SUBDIR),
  }
}

export const assertPathComponent = (value: string, label: string): void => {
  if (PATH_COMPONENT_PATTERN.exec(value)?.[0] !== value || value === "." || value === "..") {
    throw new Error(`invalid ${label}: ${value}`)
  }
}

export const harnessFromAdapter = (
  adapter: HarnessAdapter,
  userHome: string,
  sourceName: string = adapter.id,
): Harness => {
  assertPathComponent(sourceName, "harness id")
  for (const segment of adapter.homeSegments) {
    assertPathComponent(segment, `${adapter.id} home segment`)
  }
  const home = joinPath(userHome, ...adapter.homeSegments)
  const spec = adapter.launcher
  const env = typeof spec.env === "function" ? spec.env(home) : (spec.env ?? null)
  const common = { bin: spec.bin, defaultArgs: spec.defaultArgs ?? [], env }
  const launcher: HarnessLauncher =
    spec._tag === "Npm"
      ? { ...common, _tag: "Npm", package: spec.package }
      : { ...common, _tag: "StaticRelease", release: spec.release }
  return {
    id: adapter.id,
    sourceName,
    home,
    launcher,
    instructionFile:
      adapter.instructionFile === ""
        ? DEFAULT_INSTRUCTION_FILE
        : (adapter.instructionFile ?? DEFAULT_INSTRUCTION_FILE),
    runtimeSubdir: adapter.runtimeSubdir ?? null,
    preserveJsonKeys: adapter.preserveJsonKeys ?? {},
    cliproxyTemplates: adapter.cliproxyTemplates ?? [],
    cliproxyPreserveTopLevels: adapter.cliproxyPreserveTopLevels ?? {},
    pythonEnvSegments:
      (adapter.pythonEnvSegments?.length ?? 0) > 0 ? (adapter.pythonEnvSegments ?? null) : null,
    hooks: adapter.hooks ?? [],
  }
}

export const supportedHarness = (
  home: string,
  sourceName: string,
  platform: HostPlatform,
): Harness | undefined => {
  for (const adapter of HARNESS_ADAPTERS) {
    if (adapter.id === sourceName && adapter.platforms.includes(platform)) {
      return harnessFromAdapter(adapter, home, sourceName)
    }
  }
  return undefined
}

// The caller supplies names of directories, not arbitrary directory entries.
export const discoverHarnesses = (
  home: string,
  directoryNames: Iterable<string>,
  platform: HostPlatform,
): readonly Harness[] => {
  const names = new Set(directoryNames)
  const result: Harness[] = []
  for (const adapter of HARNESS_ADAPTERS) {
    if (names.has(adapter.id) && adapter.platforms.includes(platform)) {
      result.push(harnessFromAdapter(adapter, home))
    }
  }
  return result
}
export const harnessRoot = (harness: Harness): string =>
  harness.runtimeSubdir !== null && harness.runtimeSubdir !== ""
    ? joinPath(harness.home, harness.runtimeSubdir)
    : harness.home
export const harnessSourceRoot = (harness: Harness, harnessesHome: string): string => {
  const base = joinPath(harnessesHome, harness.sourceName)
  return harness.runtimeSubdir !== null && harness.runtimeSubdir !== ""
    ? joinPath(base, harness.runtimeSubdir)
    : base
}
export const harnessInstructionTarget = (harness: Harness): string =>
  joinPath(harnessRoot(harness), harness.instructionFile)
export const harnessManagedStatePath = (harness: Harness, managedStateHome: string): string =>
  joinPath(managedStateHome, `${harness.sourceName}.json`)
