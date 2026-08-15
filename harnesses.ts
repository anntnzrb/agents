/**
 * User-facing harness catalog.
 *
 * This is intentionally executable TypeScript rather than JSON/YAML: the
 * sync application imports this declaration directly, so paths and wrapper
 * behavior cannot silently drift between two config formats.
 */

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

export interface HarnessDeclaration {
  readonly homeSegments: readonly string[];
  readonly platforms: readonly HostPlatform[];
  readonly launcher: HarnessLauncherSpec;
  readonly instructionFile?: string;
  readonly assetRenames?: readonly AssetRename[];
  readonly runtimeSubdir?: string;
  readonly compatManagedEntries?: readonly string[];
  readonly hooks?: readonly HarnessHookSpec[];
}

export function defineHarnesses<const T extends Record<string, HarnessDeclaration>>(
  declarations: T,
): T {
  return declarations;
}

/** The only supported harness declaration used by sync and wrapper generation. */
export const HARNESS_CATALOG = defineHarnesses({
  codex: {
    homeSegments: [".codex"],
    platforms: ["darwin", "linux", "win32"],
    launcher: {
      package: "@openai/codex",
      bin: "codex",
    },
  },
  opencode: {
    homeSegments: [".config", "opencode"],
    platforms: ["darwin", "linux", "win32"],
    launcher: {
      package: "opencode-ai",
      bin: "opencode",
    },
  },
  pi: {
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
  omp: {
    homeSegments: [".omp"],
    platforms: ["darwin", "linux", "win32"],
    launcher: {
      package: "@oh-my-pi/pi-coding-agent",
      bin: "omp",
    },
    runtimeSubdir: "agent",
  },
});

export type HarnessId = keyof typeof HARNESS_CATALOG;

// Convenience members preserve the existing API while the record keys remain
// the authoritative ownership IDs.
export const HarnessId = {
  Codex: "codex",
  Opencode: "opencode",
  Pi: "pi",
  Omp: "omp",
} as const satisfies Record<string, HarnessId>;
