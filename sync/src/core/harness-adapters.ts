export type HostPlatform = "darwin" | "linux" | "win32";
export type AssetRename = readonly [string, string];

export interface HarnessLauncherSpec {
  readonly package: string;
  readonly bin: string;
  readonly distTag?: string;
  readonly smokeCheck?: string;
}

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

export interface HarnessAdapter {
  readonly id: string;
  readonly homeSegments: readonly string[];
  readonly platforms: readonly HostPlatform[];
  readonly launcher: HarnessLauncherSpec;
  readonly instructionFile?: string;
  readonly assetRenames?: readonly AssetRename[];
  readonly runtimeSubdir?: string;
  readonly compatManagedEntries?: readonly string[];
  readonly hooks?: readonly HarnessHookSpec[];
}

/**
 * Internal adapters for harnesses understood by sync.
 *
 * A matching directory under harnesses/ opts into an adapter. Users never need to
 * repeat launcher, platform, destination, or hook plumbing in configuration.
 */
export const HARNESS_ADAPTERS = [
  {
    id: "codex",
    homeSegments: [".codex"],
    platforms: ["darwin", "linux", "win32"],
    launcher: {
      package: "@openai/codex",
      bin: "codex",
    },
  },
  {
    id: "deepseek",
    homeSegments: [".dsh"],
    platforms: ["darwin", "linux", "win32"],
    launcher: {
      package: "@deepseek-ai/dsh",
      bin: "dsh",
    },
  },
  {
    id: "opencode",
    homeSegments: [".config", "opencode"],
    platforms: ["darwin", "linux", "win32"],
    launcher: {
      package: "opencode-ai",
      bin: "opencode",
    },
  },
  {
    id: "pi",
    homeSegments: [".pi"],
    platforms: ["darwin", "linux", "win32"],
    launcher: {
      package: "@earendil-works/pi-coding-agent",
      bin: "pi",
    },
    runtimeSubdir: "agent",
    compatManagedEntries: ["legacy"],
    hooks: [
      {
        kind: "PackageBootstrap",
        manifestFile: "packages.json",
        settingsFile: "settings.json",
        cacheSubdir: ".local/share/agents/pi-packages",
      },
      {
        kind: "ExtensionDeps",
        rootDir: "extensions",
      },
    ],
  },
  {
    id: "omp",
    homeSegments: [".omp"],
    platforms: ["darwin", "linux", "win32"],
    launcher: {
      package: "@oh-my-pi/pi-coding-agent",
      bin: "omp",
    },
    runtimeSubdir: "agent",
  },
] as const satisfies readonly HarnessAdapter[];

export type HarnessId = (typeof HARNESS_ADAPTERS)[number]["id"];
