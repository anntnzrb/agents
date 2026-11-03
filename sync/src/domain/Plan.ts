import { Schema } from "effect"

import { AgentsSettings } from "#domain/AgentsSettings"
import { Harness } from "#domain/Harness"

export const CliProxyEndpointTarget = Schema.Struct({
  src: Schema.String,
  dst: Schema.String,
  preserveTopLevels: Schema.Array(Schema.String),
})

export const DirJob = Schema.TaggedStruct("Dir", {
  src: Schema.String,
  dst: Schema.String,
  scope: Schema.Literals(["Tree", "Children"]),
  preservePaths: Schema.Array(Schema.String),
})
export const FileJob = Schema.TaggedStruct("File", {
  src: Schema.String,
  dst: Schema.String,
  endpointTemplate: Schema.Boolean,
  deployment: Schema.NullOr(AgentsSettings),
})
export const PreserveJsonKeysJob = Schema.TaggedStruct("PreserveJsonKeys", {
  src: Schema.String,
  dst: Schema.String,
  preservePaths: Schema.Array(Schema.String),
})
export const CliProxyReadinessJob = Schema.TaggedStruct("CliProxyReadiness", {
  deployment: AgentsSettings,
})
export const CliProxyEndpointTemplatesJob = Schema.TaggedStruct("CliProxyEndpointTemplates", {
  targets: Schema.Array(CliProxyEndpointTarget),
  deployment: AgentsSettings,
})
export const SyncRuntimeInstallJob = Schema.TaggedStruct("SyncRuntimeInstall", {
  sourceRoot: Schema.String,
  releasesRoot: Schema.String,
  currentLink: Schema.String,
  timeoutMs: Schema.Finite,
})
export const Job = Schema.Union([
  DirJob,
  FileJob,
  PreserveJsonKeysJob,
  CliProxyReadinessJob,
  CliProxyEndpointTemplatesJob,
  SyncRuntimeInstallJob,
])
export const ExtensionDepsHookPlan = Schema.TaggedStruct("ExtensionDeps", {
  harness: Harness,
  jobRoot: Schema.String,
  root: Schema.String,
  sourceRoot: Schema.String,
  relativeRoot: Schema.String,
  statePath: Schema.String,
  timeoutMs: Schema.Finite,
})
export const HarnessPlan = Schema.Struct({
  harness: Harness,
  statePath: Schema.String,
  root: Schema.String,
  sourceRoot: Schema.String,
  instructionTarget: Schema.String,
  currentEntryNames: Schema.Array(Schema.String),
  cleanupEntryNames: Schema.Array(Schema.String),
  hooks: Schema.Array(ExtensionDepsHookPlan),
})
export const SyncPlan = Schema.Struct({
  harnesses: Schema.Array(HarnessPlan),
  jobs: Schema.Array(Job),
  hooks: Schema.Array(ExtensionDepsHookPlan),
  cliProxyDeployment: AgentsSettings,
})

export type CliProxyEndpointTarget = typeof CliProxyEndpointTarget.Type
export type DirJob = typeof DirJob.Type
export type FileJob = typeof FileJob.Type
export type PreserveJsonKeysJob = typeof PreserveJsonKeysJob.Type
export type CliProxyReadinessJob = typeof CliProxyReadinessJob.Type
export type CliProxyEndpointTemplatesJob = typeof CliProxyEndpointTemplatesJob.Type
export type SyncRuntimeInstallJob = typeof SyncRuntimeInstallJob.Type
export type Job = typeof Job.Type
export type ExtensionDepsHookPlan = typeof ExtensionDepsHookPlan.Type
export type HarnessPlan = typeof HarnessPlan.Type
export type SyncPlan = typeof SyncPlan.Type
