import path from "node:path";

export const SOURCE_AGENT_FILE = "AGENTS.md";
const CLAUDE_AGENT_FILE = "CLAUDE.md";
const INSTALL_TIMEOUT_SECONDS = 120;
export const MANAGED_STATE_SUBDIR = ".local/share/agents/sync-managed";
const DEFAULT_PACKAGE_CACHE_SUBDIR = ".local/share/agents/pi-packages";

export type AssetRename = readonly [string, string];

const PI_COMPAT_MANAGED_ENTRIES = ["legacy"] as const;

export type HarnessHookSpec =
  | {
      readonly kind: "PackageBootstrap";
      readonly manifestFile?: string;
      readonly settingsFile?: string;
      readonly cacheSubdir?: string;
    }
  | {
      readonly kind: "ExtensionDeps";
      readonly rootDir: string;
    };

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

export enum HarnessId {
  Claude = "Claude",
  Codex = "Codex",
  Opencode = "Opencode",
  Pi = "Pi",
  Omp = "Omp",
}

export interface HarnessSpec {
  readonly id: HarnessId;
  readonly sourceName: string;
  readonly home: string;
  readonly instructionFile?: string;
  readonly assetRenames?: readonly AssetRename[];
  readonly runtimeSubdir?: string;
  readonly compatManagedEntries?: readonly string[];
  readonly hooks?: readonly HarnessHookSpec[];
}

export interface Harness {
  readonly id: HarnessId;
  readonly sourceName: string;
  readonly home: string;
  readonly instructionFile: string;
  readonly assetRenames: readonly AssetRename[];
  readonly runtimeSubdir: string | undefined;
  readonly compatManagedEntries: readonly string[];
  readonly hooks: readonly HarnessHook[];
}

export class SyncEnv {
  readonly home: string;
  readonly assetsHome: string;
  readonly toolsHome: string;
  readonly mcporterHome: string;
  readonly managedStateHome: string;
  readonly installTimeoutMs: number;
  readonly harnesses: readonly Harness[];

  constructor(
    home: string,
    assetsHome: string,
    toolsHome: string,
    mcporterHome: string,
    managedStateHome: string,
    installTimeoutMs: number,
    harnesses: readonly Harness[]
  ) {
    this.home = home;
    this.assetsHome = assetsHome;
    this.toolsHome = toolsHome;
    this.mcporterHome = mcporterHome;
    this.managedStateHome = managedStateHome;
    this.installTimeoutMs = installTimeoutMs;
    this.harnesses = harnesses;
  }

  static fromSystem(): SyncEnv {
    const home = process.env.HOME;
    if (!home) {
      throw new Error("missing HOME");
    }
    return SyncEnv.fromHome(home, INSTALL_TIMEOUT_SECONDS * 1000);
  }

  static fromHome(home: string, installTimeoutMs: number): SyncEnv {
    const agentsHome = path.join(home, ".config", "agents");
    return new SyncEnv(
      home,
      path.join(agentsHome, "assets"),
      path.join(agentsHome, "tools"),
      path.join(home, ".mcporter"),
      path.join(home, MANAGED_STATE_SUBDIR),
      installTimeoutMs,
      defaultHarnesses(home)
    );
  }

  harness(id: HarnessId): Harness | undefined {
    return this.harnesses.find((harness) => harness.id === id);
  }
}

export function buildHarness(spec: HarnessSpec): Harness {
  return {
    id: spec.id,
    sourceName: spec.sourceName,
    home: spec.home,
    instructionFile: spec.instructionFile ?? SOURCE_AGENT_FILE,
    assetRenames: spec.assetRenames ?? [],
    runtimeSubdir: spec.runtimeSubdir,
    compatManagedEntries: spec.compatManagedEntries ?? [],
    hooks: normalizeHooks(spec.hooks ?? []),
  };
}

export function defaultHarnesses(home: string): readonly Harness[] {
  const harnessSpecs: HarnessSpec[] = [
    {
      id: HarnessId.Claude,
      sourceName: "claude",
      home: path.join(home, ".claude"),
      instructionFile: CLAUDE_AGENT_FILE,
    },
    {
      id: HarnessId.Codex,
      sourceName: "codex",
      home: path.join(home, ".codex"),
    },
    {
      id: HarnessId.Opencode,
      sourceName: "opencode",
      home: path.join(home, ".config", "opencode"),
    },
    {
      id: HarnessId.Pi,
      sourceName: "pi",
      home: path.join(home, ".pi"),
      runtimeSubdir: "agent",
      compatManagedEntries: PI_COMPAT_MANAGED_ENTRIES,
      hooks: [
        {
          kind: "PackageBootstrap",
          manifestFile: "packages.json",
          settingsFile: "settings.json",
          cacheSubdir: DEFAULT_PACKAGE_CACHE_SUBDIR,
        },
        {
          kind: "ExtensionDeps",
          rootDir: "extensions",
        },
      ],
    },
    {
      id: HarnessId.Omp,
      sourceName: "omp",
      home: path.join(home, ".omp"),
      runtimeSubdir: "agent",
    },
  ];
  return harnessSpecs.map(buildHarness);
}

export function harnessRoot(harness: Harness): string {
  return harness.runtimeSubdir ? path.join(harness.home, harness.runtimeSubdir) : harness.home;
}

export function harnessSourceRoot(harness: Harness, toolsHome: string): string {
  return harness.runtimeSubdir
    ? path.join(toolsHome, harness.sourceName, harness.runtimeSubdir)
    : path.join(toolsHome, harness.sourceName);
}

export function harnessInstructionTarget(harness: Harness): string {
  return path.join(harnessRoot(harness), harness.instructionFile);
}

export function harnessInstructionFileName(harness: Harness): string {
  return harness.instructionFile;
}

export function harnessRenameAsset(harness: Harness, assetName: string): string {
  const match = harness.assetRenames.find(([src]) => src === assetName);
  return match ? match[1] : assetName;
}

export function harnessManagedStatePath(harness: Harness, managedStateHome: string): string {
  return path.join(managedStateHome, `${harness.sourceName}.json`);
}

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
    }
  });
}
