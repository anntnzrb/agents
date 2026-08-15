import { existsSync, statSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { assertNever } from "@runtime/errors.ts";
import {
  type AssetRename,
  HARNESS_ADAPTERS,
  type HarnessAdapter,
  type HarnessHookSpec,
  type HarnessId,
  type HarnessLauncherSpec,
  type HostPlatform,
} from "./harness-adapters.ts";

export type { AssetRename, HarnessId, HostPlatform } from "./harness-adapters.ts";

export const SOURCE_AGENT_FILE = "AGENTS.md";
const INSTALL_TIMEOUT_SECONDS = 120;
export const MANAGED_STATE_SUBDIR = ".local/share/agents/sync-managed";
const DEFAULT_PACKAGE_CACHE_SUBDIR = ".local/share/agents/pi-packages";
export const SKILLS_DST_DIR = "skills";
export const SKILLS_SOURCE_SUBDIR = "current";
const PATH_COMPONENT_PATTERN = /^[A-Za-z0-9._-]+$/;

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

export interface HarnessSpec extends Omit<HarnessAdapter, "homeSegments" | "id" | "platforms"> {
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
  readonly ssotHome: string;
  readonly runtimeHome: string;
  readonly assetsHome: string;
  readonly skillsHome: string;
  readonly harnessesHome: string;
  readonly mcporterHome: string;
  readonly managedStateHome: string;
  readonly installTimeoutMs: number;
  readonly harnesses: readonly Harness[];
  readonly platform: HostPlatform;
  readonly localAppData: string | undefined;

  constructor(
    home: string,
    ssotHome: string,
    runtimeHome: string,
    assetsHome: string,
    skillsHome: string,
    harnessesHome: string,
    mcporterHome: string,
    managedStateHome: string,
    installTimeoutMs: number,
    harnesses: readonly Harness[],
    platform: HostPlatform = platformFromProcess(),
    localAppData: string | undefined = process.env["LOCALAPPDATA"],
  ) {
    this.home = home;
    this.ssotHome = ssotHome;
    this.runtimeHome = runtimeHome;
    this.assetsHome = assetsHome;
    this.skillsHome = skillsHome;
    this.harnessesHome = harnessesHome;
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
    const runtimeHome = path.join(home, ".local", "share", "agents");
    const harnessesHome = path.join(agentsHome, "harnesses");
    const platform = options.platform ?? platformFromProcess();
    return new SyncEnv(
      home,
      agentsHome,
      runtimeHome,
      path.join(agentsHome, "assets"),
      path.join(agentsHome, "skills"),
      harnessesHome,
      path.join(home, ".mcporter"),
      path.join(home, MANAGED_STATE_SUBDIR),
      installTimeoutMs,
      discoverHarnesses(home, harnessesHome, platform),
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

export function discoverHarnesses(
  home: string,
  harnessesHome: string,
  platform: HostPlatform = platformFromProcess(),
): readonly Harness[] {
  return HARNESS_ADAPTERS.filter(
    (adapter) =>
      adapter.platforms.includes(platform) && isDirectory(path.join(harnessesHome, adapter.id)),
  ).map((adapter) => {
    for (const segment of adapter.homeSegments) {
      assertPathComponent(segment, `${adapter.id} home segment`);
    }
    return buildHarness({
      ...adapter,
      id: adapter.id,
      sourceName: adapter.id,
      home: path.join(home, ...adapter.homeSegments),
    });
  });
}

export function supportedHarness(
  home: string,
  sourceName: string,
  platform: HostPlatform,
): Harness | undefined {
  const adapter = HARNESS_ADAPTERS.find(
    (candidate) => candidate.id === sourceName && candidate.platforms.includes(platform),
  );
  if (!adapter) {
    return undefined;
  }
  return buildHarness({
    ...adapter,
    id: adapter.id,
    sourceName: adapter.id,
    home: path.join(home, ...adapter.homeSegments),
  });
}

function isDirectory(candidate: string): boolean {
  return existsSync(candidate) && statSync(candidate).isDirectory();
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

export function harnessSourceRoot(harness: Harness, harnessesHome: string): string {
  return harness.runtimeSubdir
    ? path.join(harnessesHome, harness.sourceName, harness.runtimeSubdir)
    : path.join(harnessesHome, harness.sourceName);
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
