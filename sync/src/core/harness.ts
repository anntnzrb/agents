import { existsSync, readFileSync, statSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { assertNever, isErrno } from "@runtime/errors.ts";
import { ConfigProvider, Effect, HashMap, Schema } from "effect";
import {
  HARNESS_ADAPTERS,
  type HarnessAdapter,
  type HarnessHookSpec,
  type HarnessId,
  type HarnessLauncherSpec,
  type HostPlatform,
} from "./harness-adapters.ts";

export type { HarnessId, HostPlatform } from "./harness-adapters.ts";

export const SOURCE_AGENT_FILE = "HARNESS.md";
const DEFAULT_INSTRUCTION_FILE = "AGENTS.md";
const INSTALL_TIMEOUT_SECONDS = 120;
export const MANAGED_STATE_SUBDIR = ".local/share/agentium/sync-managed";
const DEFAULT_PACKAGE_CACHE_SUBDIR = ".local/share/agentium/pi-packages";
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
  readonly launcher: Required<Omit<HarnessLauncherSpec, "env">> & {
    readonly env?: Record<string, string>;
  };
  readonly instructionFile: string;
  readonly runtimeSubdir: string | undefined;
  readonly compatManagedEntries: readonly string[];
  readonly hooks: readonly HarnessHook[];
}

export class SyncEnv {
  readonly home: string;
  readonly ssotHome: string;
  readonly dataHome: string;
  readonly skillsHome: string;
  readonly harnessesHome: string;
  readonly mcporterHome: string;
  readonly summarizeHome: string;
  readonly managedStateHome: string;
  readonly installTimeoutMs: number;
  readonly harnesses: readonly Harness[];
  readonly platform: HostPlatform;
  readonly rootEnv: Readonly<Record<string, string>>;

  constructor(
    home: string,
    ssotHome: string,
    dataHome: string,
    skillsHome: string,
    harnessesHome: string,
    mcporterHome: string,
    summarizeHome: string,
    managedStateHome: string,
    installTimeoutMs: number,
    harnesses: readonly Harness[],
    platform: HostPlatform = platformFromProcess(),
  ) {
    this.home = home;
    this.ssotHome = ssotHome;
    this.rootEnv = Effect.runSync(loadRootEnv(path.join(ssotHome, ".env")));
    this.dataHome = dataHome;
    this.skillsHome = skillsHome;
    this.harnessesHome = harnessesHome;
    this.mcporterHome = mcporterHome;
    this.summarizeHome = summarizeHome;
    this.managedStateHome = managedStateHome;
    this.installTimeoutMs = installTimeoutMs;
    this.harnesses = harnesses;
    this.platform = platform;
  }

  static fromSystem(): SyncEnv {
    const homeCandidates = [Bun.env["HOME"], process.env["HOME"], os.homedir()];
    const home = homeCandidates.find(
      (candidate): candidate is string =>
        typeof candidate === "string" && candidate.trim().length > 0,
    );
    if (!home) {
      throw new Error("missing HOME");
    }
    return SyncEnv.fromHome(home, INSTALL_TIMEOUT_SECONDS * 1000);
  }

  static fromHome(
    home: string,
    installTimeoutMs: number,
    options: {
      readonly platform?: HostPlatform;
    } = {},
  ): SyncEnv {
    const agentsHome = path.join(home, ".config", "agents");
    const dataHome = path.join(home, ".local", "share", "agentium");
    const harnessesHome = path.join(agentsHome, "harnesses");
    const platform = options.platform ?? platformFromProcess();
    return new SyncEnv(
      home,
      agentsHome,
      dataHome,
      path.join(agentsHome, "skills"),
      harnessesHome,
      path.join(home, ".mcporter"),
      path.join(home, ".summarize"),
      path.join(home, MANAGED_STATE_SUBDIR),
      installTimeoutMs,
      discoverHarnesses(home, harnessesHome, platform),
      platform,
    );
  }

  harness(id: HarnessId): Harness | undefined {
    return this.harnesses.find((harness) => harness.id === id);
  }
}

export class RootEnvReadError extends Schema.TaggedError<RootEnvReadError>()("RootEnvReadError", {
  path: Schema.String,
  cause: Schema.Unknown,
}) {
  override get message(): string {
    return `failed to read root environment file ${this.path}`;
  }
}

const readRootEnvContent = (envPath: string): Effect.Effect<string | undefined, RootEnvReadError> =>
  Effect.try({
    try: () => readFileSync(envPath, "utf-8"),
    catch: (cause) => ({ cause, isEnoent: isErrno(cause, "ENOENT") }),
  }).pipe(
    Effect.catchIf(
      ({ isEnoent }) => isEnoent,
      () => Effect.succeed(undefined),
    ),
    Effect.mapError(({ cause }) => new RootEnvReadError({ path: envPath, cause })),
  );

const collectEnvFromProvider = (
  provider: ConfigProvider.ConfigProvider,
  currentPath: readonly string[] = [],
): Effect.Effect<HashMap.HashMap<string, string>, ConfigProvider.SourceError> =>
  Effect.gen(function* () {
    const node = yield* provider.load(currentPath);
    if (!node) {
      return HashMap.empty<string, string>();
    }

    let current = HashMap.empty<string, string>();
    if (node.value !== undefined && currentPath.length > 0) {
      current = HashMap.set(current, currentPath.join("_"), node.value);
    } else if (node._tag === "Value" && currentPath.length > 0) {
      current = HashMap.set(current, currentPath.join("_"), node.value);
    }

    const childSegments: readonly string[] =
      node._tag === "Record"
        ? Array.from(node.keys)
        : node._tag === "Array"
          ? Array.from({ length: node.length }, (_, i) => String(i))
          : [];

    if (childSegments.length === 0) {
      return current;
    }

    const childMaps = yield* Effect.forEach(childSegments, (segment) =>
      collectEnvFromProvider(provider, [...currentPath, segment]),
    );

    return childMaps.reduce((acc, childMap) => HashMap.union(acc, childMap), current);
  });

export const decodeRootEnv = (
  content: string | undefined,
): Effect.Effect<Readonly<Record<string, string>>, ConfigProvider.SourceError> =>
  Effect.gen(function* () {
    if (content === undefined) {
      return Object.freeze({});
    }

    const provider = ConfigProvider.fromDotEnvContents(content, {
      expandVariables: false,
      preserveEmptyStrings: false,
    });

    const hashMap = yield* collectEnvFromProvider(provider);
    return Object.freeze(Object.fromEntries(HashMap.toEntries(hashMap)));
  });

export const loadRootEnv = (
  envPath: string,
): Effect.Effect<Readonly<Record<string, string>>, RootEnvReadError | ConfigProvider.SourceError> =>
  readRootEnvContent(envPath).pipe(Effect.andThen(decodeRootEnv));

export function buildHarness(spec: HarnessSpec): Harness {
  assertPathComponent(spec.sourceName, "harness id");
  const env =
    typeof spec.launcher.env === "function" ? spec.launcher.env(spec.home) : spec.launcher.env;
  return {
    id: spec.id,
    sourceName: spec.sourceName,
    home: spec.home,
    launcher: {
      package: spec.launcher.package,
      bin: spec.launcher.bin,
      distTag: spec.launcher.distTag ?? "latest",
      smokeCheck: spec.launcher.smokeCheck ?? "--version",
      defaultArgs: spec.launcher.defaultArgs ?? [],
      ...(env === undefined ? {} : { env }),
    },
    instructionFile: spec.instructionFile ?? DEFAULT_INSTRUCTION_FILE,
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
  if (process.platform === "darwin" || process.platform === "linux") {
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
