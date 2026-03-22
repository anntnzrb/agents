import path from "node:path";

export const SOURCE_AGENT_FILE = "AGENTS.md";
const CLAUDE_AGENT_FILE = "CLAUDE.md";
const INSTALL_TIMEOUT_SECONDS = 120;
export const MANAGED_STATE_SUBDIR = ".local/share/agents/sync-managed";

export type AssetRename = readonly [string, string];

const PI_COMPAT_MANAGED_ENTRIES = ["legacy"] as const;

export enum HarnessId {
  Claude = "Claude",
  Codex = "Codex",
  Opencode = "Opencode",
  Pi = "Pi",
  Omp = "Omp",
}

export class Harness {
  readonly id: HarnessId;
  readonly sourceName: string;
  readonly home: string;
  readonly instructionFile: string;
  readonly assetRenames: readonly AssetRename[];
  readonly runtimeSubdir: string | undefined;
  readonly compatManagedEntries: readonly string[];

  constructor(
    id: HarnessId,
    sourceName: string,
    home: string,
    instructionFile = SOURCE_AGENT_FILE,
    assetRenames: readonly AssetRename[] = [],
    runtimeSubdir?: string,
    compatManagedEntries: readonly string[] = []
  ) {
    this.id = id;
    this.sourceName = sourceName;
    this.home = home;
    this.instructionFile = instructionFile;
    this.assetRenames = assetRenames;
    this.runtimeSubdir = runtimeSubdir;
    this.compatManagedEntries = compatManagedEntries;
  }

  withInstructionFile(instructionFile: string): Harness {
    return new Harness(
      this.id,
      this.sourceName,
      this.home,
      instructionFile,
      this.assetRenames,
      this.runtimeSubdir,
      this.compatManagedEntries
    );
  }

  withRuntimeSubdir(runtimeSubdir: string): Harness {
    return new Harness(
      this.id,
      this.sourceName,
      this.home,
      this.instructionFile,
      this.assetRenames,
      runtimeSubdir,
      this.compatManagedEntries
    );
  }

  withCompatManagedEntries(compatManagedEntries: readonly string[]): Harness {
    return new Harness(
      this.id,
      this.sourceName,
      this.home,
      this.instructionFile,
      this.assetRenames,
      this.runtimeSubdir,
      compatManagedEntries
    );
  }

  root(): string {
    return this.runtimeSubdir ? path.join(this.home, this.runtimeSubdir) : this.home;
  }

  sourceRoot(toolsHome: string): string {
    return this.runtimeSubdir
      ? path.join(toolsHome, this.sourceName, this.runtimeSubdir)
      : path.join(toolsHome, this.sourceName);
  }

  instructionFileName(): string {
    return this.instructionFile;
  }

  instructionTarget(): string {
    return path.join(this.root(), this.instructionFile);
  }

  renameAsset(assetName: string): string {
    const match = this.assetRenames.find(([src]) => src === assetName);
    return match ? match[1] : assetName;
  }

  managedStatePath(managedStateHome: string): string {
    return path.join(managedStateHome, `${this.sourceName}.json`);
  }
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
      [
        new Harness(HarnessId.Claude, "claude", path.join(home, ".claude")).withInstructionFile(
          CLAUDE_AGENT_FILE
        ),
        new Harness(HarnessId.Codex, "codex", path.join(home, ".codex")),
        new Harness(HarnessId.Opencode, "opencode", path.join(home, ".config", "opencode")),
        new Harness(HarnessId.Pi, "pi", path.join(home, ".pi"))
          .withRuntimeSubdir("agent")
          .withCompatManagedEntries(PI_COMPAT_MANAGED_ENTRIES),
        new Harness(HarnessId.Omp, "omp", path.join(home, ".omp")).withRuntimeSubdir("agent"),
      ]
    );
  }

  harness(id: HarnessId): Harness | undefined {
    return this.harnesses.find((harness) => harness.id === id);
  }
}
