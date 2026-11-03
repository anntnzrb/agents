import { Schema } from "effect"

export const HostPlatform = Schema.Literals(["darwin", "linux"])
export type HostPlatform = typeof HostPlatform.Type
export const HarnessId = Schema.Literals(["amp", "claude", "codex", "devin", "opencode", "pi", "omp"])
export type HarnessId = typeof HarnessId.Type
export const DEFAULT_INSTRUCTION_FILE = "AGENTS.md"

export const StaticRelease = Schema.Struct({
  manifestUrl: Schema.String,
  installSegments: Schema.Array(Schema.String),
  executableSegments: Schema.Array(Schema.String),
  targets: Schema.Record(Schema.String, Schema.String),
  manSegments: Schema.NullOr(Schema.Array(Schema.String)),
  manDestSegments: Schema.NullOr(Schema.Array(Schema.String)),
})
export type StaticRelease = typeof StaticRelease.Type
export const ExtensionDepsHook = Schema.Struct({
  kind: Schema.Literal("ExtensionDeps"),
  rootDir: Schema.String,
})
export type ExtensionDepsHook = typeof ExtensionDepsHook.Type

export type LauncherEnv =
  | Readonly<Record<string, string>>
  | ((home: string) => Readonly<Record<string, string>>)
export interface NpmLauncherSpec {
  readonly _tag: "Npm"
  readonly package: string
  readonly bin: string
  readonly defaultArgs?: readonly string[]
  readonly env?: LauncherEnv
}
export interface StaticReleaseLauncherSpec {
  readonly _tag: "StaticRelease"
  readonly bin: string
  readonly release: StaticRelease
  readonly defaultArgs?: readonly string[]
  readonly env?: LauncherEnv
}
export type HarnessLauncherSpec = NpmLauncherSpec | StaticReleaseLauncherSpec
export interface HarnessAdapter {
  readonly id: HarnessId
  readonly homeSegments: readonly string[]
  readonly platforms: readonly HostPlatform[]
  readonly launcher: HarnessLauncherSpec
  readonly instructionFile?: string
  readonly runtimeSubdir?: string
  readonly preserveJsonKeys?: Readonly<Record<string, readonly string[]>>
  readonly cliproxyTemplates?: readonly string[]
  readonly cliproxyPreserveTopLevels?: Readonly<Record<string, readonly string[]>>
  readonly pythonEnvSegments?: readonly string[]
  readonly hooks?: readonly ExtensionDepsHook[]
}

const platforms = ["darwin", "linux"] as const
export const HARNESS_ADAPTERS: readonly HarnessAdapter[] = [
  {
    id: "codex",
    homeSegments: [".codex"],
    platforms,
    launcher: { _tag: "Npm", package: "@openai/codex", bin: "codex" },
    cliproxyTemplates: ["config.toml"],
    cliproxyPreserveTopLevels: { "config.toml": ["hooks.state", "projects"] },
  },
  {
    id: "devin",
    homeSegments: [".config", "devin"],
    platforms,
    launcher: {
      _tag: "StaticRelease",
      bin: "devin",
      env: { DEVIN_PERMISSION_MODE: "bypass" },
      release: {
        manifestUrl: "https://static.devin.ai/cli/current/manifest.json",
        installSegments: [".local", "share", "devin", "cli"],
        executableSegments: ["bin", "devin"],
        targets: {
          "darwin-arm64": "aarch64-apple-darwin",
          "darwin-x64": "x86_64-apple-darwin",
          "linux-arm64": "aarch64-unknown-linux",
          "linux-x64": "x86_64-unknown-linux",
        },
        manSegments: ["share", "man", "man1"],
        manDestSegments: [".local", "share", "man", "man1"],
      },
    },
    preserveJsonKeys: {
      "config.json": ["devin", "shell.setup_complete", "shell.startup_messages_remaining"],
    },
  },
  {
    id: "opencode",
    homeSegments: [".config", "opencode"],
    platforms,
    launcher: { _tag: "Npm", package: "@opencode/cli", bin: "opencode" },
    cliproxyTemplates: ["opencode.jsonc"],
    hooks: [{ kind: "ExtensionDeps", rootDir: "." }],
  },
  {
    id: "pi",
    homeSegments: [".pi"],
    platforms,
    launcher: { _tag: "Npm", package: "@earendil-works/pi-coding-agent", bin: "pi" },
    runtimeSubdir: "agent",
    cliproxyTemplates: ["extensions/cliproxy/index.ts"],
    hooks: [{ kind: "ExtensionDeps", rootDir: "extensions" }],
  },
  {
    id: "omp",
    homeSegments: [".omp"],
    platforms,
    launcher: { _tag: "Npm", package: "@oh-my-pi/pi-coding-agent", bin: "omp" },
    runtimeSubdir: "agent",
    cliproxyTemplates: ["models.yml"],
    pythonEnvSegments: [".omp", "python-env"],
    hooks: [{ kind: "ExtensionDeps", rootDir: "." }],
  },
  {
    id: "amp",
    homeSegments: [".config", "amp"],
    platforms,
    launcher: {
      _tag: "Npm",
      package: "@ampcode/cli",
      bin: "amp",
      defaultArgs: ["--remote-control-terminal"],
    },
  },
  {
    id: "claude",
    homeSegments: [".claude"],
    platforms,
    launcher: { _tag: "Npm", package: "@anthropic-ai/claude-code", bin: "claude" },
    instructionFile: "CLAUDE.md",
    cliproxyTemplates: ["settings.json"],
  },
]
