import os from "node:os";
import path from "node:path";
import {
  type AssetRename,
  HARNESS_CATALOG,
  type HarnessDeclaration,
  type HarnessId,
  type HarnessLauncherSpec,
  type HostPlatform,
} from "@catalog";
import { assertNever } from "@runtime/errors.ts";

export {
  type AssetRename,
  HARNESS_CATALOG,
  HarnessId,
  type HostPlatform,
} from "@catalog";

export const SOURCE_AGENT_FILE = "AGENTS.md";
const INSTALL_TIMEOUT_SECONDS = 120;
export const MANAGED_STATE_SUBDIR = ".local/share/agents/sync-managed";
const DEFAULT_PACKAGE_CACHE_SUBDIR = ".local/share/agents/pi-packages";
export const SKILLS_DST_DIR = "skills";
export const SKILLS_SOURCE_SUBDIR = "current";
const PATH_COMPONENT_PATTERN = /^[A-Za-z0-9._-]+$/;

export type HarnessHookSpec = NonNullable<HarnessDeclaration["hooks"]>[number];

export type HarnessHook =
  | {
      readonly kind: "PackageBootstrap";
      readonly manifestFile: string;
      readonly settingsFile: string;
      readonly cacheSubdir: string;
    }
  | {
      readonly kind: "ExtensionDeps";
      readonly rootDir: string;
    };

export interface HarnessSpec extends Omit<HarnessDeclaration, "homeSegments" | "platforms"> {
  readonly id: HarnessId;
  readonly sourceName: string;
  readonly home: string;
}

export interface Harness {
  readonly id: HarnessId;
  readonly sourceName: string;
  readonly home: string;
  readonly launcher: Required<HarnessLauncherSpec>;
  readonly instructionFile: string;
  readonly assetRenames: readonly AssetRename[];
  readonly runtimeSubdir: string | undefined;
  readonly compatManagedEntries: readonly string[];
  readonly hooks: readonly HarnessHook[];
}

export class SyncEnv {
  readonly home: string;
  readonly assetsHome: string;
  readonly skillsHome: string;
  readonly toolsHome: string;
  readonly mcporterHome: string;
  readonly managedStateHome: string;
  readonly installTimeoutMs: number;
  readonly harnesses: readonly Harness[];
  readonly platform: HostPlatform;
  readonly localAppData: string | undefined;

  constructor(
    home: string,
    assetsHome: string,
    skillsHome: string,
    toolsHome: string,
    mcporterHome: string,
    managedStateHome: string,
    installTimeoutMs: number,
    harnesses: readonly Harness[],
    platform: HostPlatform = platformFromProcess(),
    localAppData: string | undefined = process.env["LOCALAPPDATA"],
  ) {
    this.home = home;
    this.assetsHome = assetsHome;
    this.skillsHome = skillsHome;
    this.toolsHome = toolsHome;
    this.mcporterHome = mcporterHome;
    this.managedStateHome = managedStateHome;
    this.installTimeoutMs = installTimeoutMs;
    this.harnesses = harnesses;
    this.platform = platform;
    this.localAppData = localAppData;
  }

  static fromSystem(): SyncEnv {
    const homeCandidates =
      process.platform === "win32"
        ? [process.env["USERPROFILE"], process.env["HOME"], os.homedir()]
        : [process.env["HOME"], process.env["USERPROFILE"], os.homedir()];
    const home = homeCandidates.find(
      (candidate): candidate is string =>
        typeof candidate === "string" && candidate.trim().length > 0,
    );
    if (!home) {
      throw new Error("missing HOME/USERPROFILE");
    }
    return SyncEnv.fromHome(home, INSTALL_TIMEOUT_SECONDS * 1000);
  }

  static fromHome(
    home: string,
    installTimeoutMs: number,
    options: {
      readonly platform?: HostPlatform;
      readonly localAppData?: string;
    } = {},
  ): SyncEnv {
    const agentsHome = path.join(home, ".config", "agents");
    const platform = options.platform ?? platformFromProcess();
    return new SyncEnv(
      home,
      path.join(agentsHome, "assets"),
      path.join(agentsHome, "skills"),
      path.join(agentsHome, "tools"),
      path.join(home, ".mcporter"),
      path.join(home, MANAGED_STATE_SUBDIR),
      installTimeoutMs,
      defaultHarnesses(home, platform),
      platform,
      options.localAppData ?? (platform === "win32" ? process.env["LOCALAPPDATA"] : undefined),
    );
  }

  harness(id: HarnessId): Harness | undefined {
    return this.harnesses.find((harness) => harness.id === id);
  }
}

export function buildHarness(spec: HarnessSpec): Harness {
  assertPathComponent(spec.sourceName, "harness id");
  return {
    id: spec.id,
    sourceName: spec.sourceName,
    home: spec.home,
    launcher: {
      package: spec.launcher.package,
      bin: spec.launcher.bin,
      distTag: spec.launcher.distTag ?? "latest",
      smokeCheck: spec.launcher.smokeCheck ?? "--version",
    },
    instructionFile: spec.instructionFile ?? SOURCE_AGENT_FILE,
    assetRenames: spec.assetRenames ?? [],
    runtimeSubdir: spec.runtimeSubdir,
    compatManagedEntries: spec.compatManagedEntries ?? [],
    hooks: normalizeHooks(spec.hooks ?? []),
  };
}

export function defaultHarnesses(
  home: string,
  platform: HostPlatform = platformFromProcess(),
): readonly Harness[] {
  return (Object.entries(HARNESS_CATALOG) as readonly [HarnessId, HarnessDeclaration][])
    .filter(([, entry]) => entry.platforms.includes(platform))
    .map(([id, entry]) => {
      for (const segment of entry.homeSegments) {
        assertPathComponent(segment, `${id} home segment`);
      }
      return buildHarness({
        ...entry,
        id,
        sourceName: id,
        home: path.join(home, ...entry.homeSegments),
      });
    });
}

function platformFromProcess(): HostPlatform {
  if (
    process.platform === "darwin" ||
    process.platform === "linux" ||
    process.platform === "win32"
  ) {
    return process.platform;
  }
  throw new Error(`unsupported platform: ${process.platform}`);
}

function assertPathComponent(value: string, label: string): void {
  if (!PATH_COMPONENT_PATTERN.test(value) || value === "." || value === "..") {
    throw new Error(`invalid ${label}: ${value}`);
  }
}

export const harnessRoot = (harness: Harness): string =>
  harness.runtimeSubdir ? path.join(harness.home, harness.runtimeSubdir) : harness.home;

export function harnessSourceRoot(harness: Harness, toolsHome: string): string {
  return harness.runtimeSubdir
    ? path.join(toolsHome, harness.sourceName, harness.runtimeSubdir)
    : path.join(toolsHome, harness.sourceName);
}

export const harnessInstructionTarget = (harness: Harness): string =>
  path.join(harnessRoot(harness), harness.instructionFile);

export const harnessInstructionFileName = (harness: Harness): string => harness.instructionFile;

export function harnessRenameAsset(harness: Harness, assetName: string): string {
  const match = harness.assetRenames.find(([src]) => src === assetName);
  return match ? match[1] : assetName;
}

export const harnessManagedStatePath = (harness: Harness, managedStateHome: string): string =>
  path.join(managedStateHome, `${harness.sourceName}.json`);

function normalizeHooks(hooks: readonly HarnessHookSpec[]): HarnessHook[] {
  return hooks.map((hook) => {
    switch (hook.kind) {
      case "PackageBootstrap":
        return {
          kind: hook.kind,
          manifestFile: hook.manifestFile ?? "packages.json",
          settingsFile: hook.settingsFile ?? "settings.json",
          cacheSubdir: hook.cacheSubdir ?? DEFAULT_PACKAGE_CACHE_SUBDIR,
        };
      case "ExtensionDeps":
        return {
          kind: hook.kind,
          rootDir: hook.rootDir,
        };
      default:
        return assertNever(hook);
    }
  });
}
