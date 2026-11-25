import { expect, test } from "bun:test"

import { Array as Arr, Effect, Schema } from "effect"

import {
  Harness,
  assertPathComponent,
  discoverHarnesses,
  harnessFromAdapter,
  harnessInstructionTarget,
  harnessManagedStatePath,
  harnessRoot,
  harnessSourceRoot,
  supportedHarness,
  syncEnvPaths,
} from "#domain/Harness"
import { HARNESS_ADAPTERS } from "#domain/HarnessAdapters"
import type { HarnessAdapter } from "#domain/HarnessAdapters"
import { TOOL_LAUNCHERS, toolLauncher, toolLauncherDefaultArgs } from "#domain/ToolLaunchers"

test("derives sync paths from the user home", () => {
  expect(syncEnvPaths("/home/user")).toEqual({
    home: "/home/user",
    ssotHome: "/home/user/src/agents",
    runtimeHome: "/home/user/.local/share/agents",
    skillsHome: "/home/user/src/agents/skills",
    harnessesHome: "/home/user/src/agents/harnesses",
    mcporterHome: "/home/user/.mcporter",
    summarizeHome: "/home/user/.summarize",
    managedStateHome: "/home/user/.local/share/agents/sync-managed",
  })
})

test("discovery follows registry order and ignores unknown directories", () => {
  expect(Arr.map(discoverHarnesses("/home/user", ["pi", "unknown", "codex"], "linux"), (h) => h.id)).toEqual([
    "codex",
    "pi",
  ])
  expect(supportedHarness("/home/user", "unknown", "linux")).toBeUndefined()
  expect(Arr.map((a: (typeof HARNESS_ADAPTERS)[number]) => a.id)(HARNESS_ADAPTERS)).toEqual([
    "codex",
    "devin",
    "opencode",
    "pi",
    "omp",
    "amp",
    "claude",
  ])
  const bins = [
    ...Arr.map((a: (typeof HARNESS_ADAPTERS)[number]) => a.launcher.bin)(HARNESS_ADAPTERS),
    ...Arr.map((t: (typeof TOOL_LAUNCHERS)[number]) => t.bin)(TOOL_LAUNCHERS),
  ]
  expect(new Set(bins).size).toBe(bins.length)
})

test("resolves release metadata, permissions, and preserved settings", () => {
  const devin = supportedHarness("/home/user", "devin", "linux")
  if (devin === undefined) {
    throw new Error("missing devin")
  }
  expect(devin?.home).toBe("/home/user/.config/devin")
  expect(devin?.preserveJsonKeys).toEqual({
    "config.json": ["devin", "shell.setup_complete", "shell.startup_messages_remaining"],
  })
  expect(devin?.launcher).toEqual({
    _tag: "StaticRelease",
    bin: "devin",
    defaultArgs: [],
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
  })
  expect(Effect.runSync(Schema.decodeEffect(Harness)(devin))).toEqual(devin)
})

test("resolves instruction and runtime paths and launcher defaults", () => {
  const pi = supportedHarness("/home/user", "pi", "darwin")
  if (pi === undefined) {
    throw new Error("missing pi")
  }
  expect(harnessRoot(pi)).toBe("/home/user/.pi/agent")
  expect(harnessSourceRoot(pi, "/repo/harnesses")).toBe("/repo/harnesses/pi/agent")
  expect(harnessInstructionTarget(pi)).toBe("/home/user/.pi/agent/AGENTS.md")
  expect(harnessManagedStatePath(pi, "/state")).toBe("/state/pi.json")
  expect(supportedHarness("/home/user", "claude", "linux")?.instructionFile).toBe("CLAUDE.md")
  expect(supportedHarness("/home/user", "amp", "linux")?.launcher.defaultArgs).toEqual([
    "--remote-control-terminal",
  ])
  expect(supportedHarness("/home/user", "omp", "linux")?.pythonEnvSegments).toEqual([".omp", "python-env"])
})

test("resolves callable environment against harness home and rejects unsafe components", () => {
  const adapter: HarnessAdapter = {
    id: "codex",
    homeSegments: [".codex"],
    platforms: ["linux"],
    launcher: { _tag: "Npm", package: "example", bin: "codex", env: (home) => ({ HOME_FOR_TOOL: home }) },
  }
  expect(harnessFromAdapter(adapter, "/home/user").launcher.env).toEqual({
    HOME_FOR_TOOL: "/home/user/.codex",
  })
  for (const value of ["", ".", "..", "../codex", "codex\n"]) {
    expect(() => {
      assertPathComponent(value, "harness id")
    }).toThrow()
  }
  expect(() => harnessFromAdapter(adapter, "/home/user", "../codex")).toThrow()
})

test("tool launchers include config and exact defaults", () => {
  const mcporter = toolLauncher("mcporter")
  const summarize = toolLauncher("summarize")
  if (mcporter === undefined || summarize === undefined) {
    throw new Error("missing tool")
  }
  expect(toolLauncherDefaultArgs({ home: "/home/user" }, mcporter)).toEqual([
    "--config",
    "/home/user/.mcporter/mcporter.json",
  ])
  expect(toolLauncherDefaultArgs({ home: "/home/user" }, summarize)).toEqual([
    "--force-summary",
    "--timestamps",
    "--format",
    "md",
    "--retries",
    "2",
    "--metrics",
    "detailed",
  ])
  expect(toolLauncher("missing")).toBeUndefined()
})
