import fs from "node:fs";
import { join, posix } from "node:path";
import { assertNever, panicMessage } from "@runtime/errors.ts";
import {
  CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER,
  CLI_PROXY_SOURCE_DIR,
  type CliProxyDeployment,
  type CliProxyEndpointTarget,
  isCliProxyGatewayHost,
  readCliProxyDeployment,
} from "./cliproxy-deployment.ts";
import {
  type Harness,
  harnessInstructionFileName,
  harnessInstructionTarget,
  harnessManagedStatePath,
  harnessRoot,
  harnessSourceRoot,
  SKILLS_DST_DIR,
  SKILLS_SOURCE_SUBDIR,
  SOURCE_AGENT_FILE,
  type SyncEnv,
} from "./harness.ts";

export type JobKind =
  | "File"
  | "Dir"
  | "SecretTemplate"
  | "CliProxyReadiness"
  | "CliProxyEndpointTemplates"
  | "CliProxyConfig"
  | "SyncRuntimeInstall";

export type Job =
  | {
      readonly kind: "CliProxyReadiness";
      readonly deployment: CliProxyDeployment;
      readonly gatewayHost: boolean;
    }
  | {
      readonly src: string;
      readonly dst: string;
      readonly kind: "File";
    }
  | {
      readonly src: string;
      readonly dst: string;
      readonly kind: "Dir";
      readonly scope?: "Tree" | "Children";
      readonly preservePaths?: readonly string[];
    }
  | {
      readonly src: string;
      readonly dst: string;
      readonly kind: "SecretTemplate";
      readonly secretsPath: string;
    }
  | {
      readonly kind: "CliProxyEndpointTemplates";
      readonly targets: readonly CliProxyEndpointTarget[];
      readonly deployment: CliProxyDeployment;
    }
  | {
      readonly src: string;
      readonly dst: string;
      readonly kind: "CliProxyConfig";
      readonly secretsPath: string;
      readonly deployment: CliProxyDeployment;
      readonly gatewayHost?: boolean;
      readonly cacheRoot?: string;
      readonly runtimeRoot?: string;
    }
  | {
      readonly kind: "SyncRuntimeInstall";
      readonly sourceRoot: string;
      readonly releasesRoot: string;
      readonly currentLink: string;
      readonly timeoutMs: number;
    };

export interface SyncRuntimeInstallJob {
  readonly kind: "SyncRuntimeInstall";
  readonly sourceRoot: string;
  readonly releasesRoot: string;
  readonly currentLink: string;
  readonly timeoutMs: number;
}

export interface HarnessPlan {
  readonly harness: Harness;
  readonly statePath: string;
  readonly root: string;
  readonly sourceRoot: string;
  readonly instructionTarget: string;
  readonly currentEntryNames: readonly string[];
  readonly cleanupEntryNames: readonly string[];
  readonly hooks: readonly SyncHookPlan[];
}

export interface SyncPlan {
  readonly harnesses: readonly HarnessPlan[];
  readonly jobs: readonly Job[];
  readonly hooks: readonly SyncHookPlan[];
  readonly cliProxyDeployment: CliProxyDeployment;
  readonly gatewayHost: boolean;
}

export type SyncHookPlan = PackageBootstrapHookPlan | ExtensionDepsHookPlan;

export interface PackageBootstrapHookPlan {
  readonly kind: "PackageBootstrap";
  readonly harness: Harness;
  readonly manifestPath: string;
  readonly runtimeSettingsPath: string;
  readonly cacheRoot: string;
  readonly timeoutMs: number;
}

export interface ExtensionDepsHookPlan {
  readonly kind: "ExtensionDeps";
  readonly harness: Harness;
  readonly jobRoot: string;
  readonly root: string;
  readonly sourceRoot: string;
  readonly relativeRoot: string;
  readonly statePath: string;
  readonly timeoutMs: number;
}

export function buildSyncPlan(syncEnv: SyncEnv): SyncPlan {
  const harnesses = syncEnv.harnesses.map((harness) => buildHarnessPlan(syncEnv, harness));
  const cliProxyDeployment = readCliProxyDeployment(
    join(syncEnv.ssotHome, CLI_PROXY_SOURCE_DIR, "deployment.json"),
  );
  const gatewayHost = isCliProxyGatewayHost(cliProxyDeployment);
  return {
    harnesses,
    jobs: [
      ...runtimeJobs(syncEnv),
      ...harnessDirJobs(harnesses),
      ...skillsJobs(syncEnv, harnesses),
      ...instructionJobs(syncEnv, harnesses),
      ...configJobs(syncEnv, harnesses, cliProxyDeployment, gatewayHost),
    ],
    hooks: harnesses.flatMap((plan) => plan.hooks),
    cliProxyDeployment,
    gatewayHost,
  };
}

function runtimeJobs(syncEnv: SyncEnv): Job[] {
  const sourceRoot = join(syncEnv.ssotHome, "sync");
  return [
    {
      kind: "SyncRuntimeInstall",
      sourceRoot,
      releasesRoot: join(syncEnv.runtimeHome, "sync-releases"),
      currentLink: join(syncEnv.runtimeHome, "sync-current"),
      timeoutMs: syncEnv.installTimeoutMs,
    },
  ];
}

export const topLevelEntryNames = (root: string): string[] => dirEntryNames(root);

function buildHarnessPlan(syncEnv: SyncEnv, harness: Harness): HarnessPlan {
  const root = harnessRoot(harness);
  const sourceRoot = harnessSourceRoot(harness, syncEnv.harnessesHome);
  const instructionTarget = harnessInstructionTarget(harness);
  const currentEntryNames = currentManagedEntryNames(
    harness,
    sourceRoot,
    skillsSourceExists(syncEnv),
  );
  const cleanupEntryNames = uniqueSorted([...currentEntryNames, ...harness.compatManagedEntries]);
  const skillHook = buildSkillHookPlan(syncEnv, harness, root);
  const hooks = [
    ...buildHookPlans(syncEnv, harness, root, sourceRoot),
    ...(skillHook === undefined ? [] : [skillHook]),
  ];
  return {
    harness,
    statePath: harnessManagedStatePath(harness, syncEnv.managedStateHome),
    root,
    sourceRoot,
    instructionTarget,
    currentEntryNames,
    cleanupEntryNames,
    hooks,
  };
}

function buildSkillHookPlan(
  syncEnv: SyncEnv,
  harness: Harness,
  root: string,
): ExtensionDepsHookPlan | undefined {
  if (!skillsSourceExists(syncEnv)) {
    return undefined;
  }
  const skillsSource = join(syncEnv.skillsHome, SKILLS_SOURCE_SUBDIR);
  return {
    kind: "ExtensionDeps",
    harness,
    jobRoot: join(root, SKILLS_DST_DIR),
    root: join(root, SKILLS_DST_DIR),
    sourceRoot: skillsSource,
    relativeRoot: "",
    statePath: join(syncEnv.managedStateHome, `${harness.sourceName}.skills-deps.json`),
    timeoutMs: syncEnv.installTimeoutMs,
  };
}

function currentManagedEntryNames(
  harness: Harness,
  sourceRoot: string,
  hasSkillsSource: boolean,
): string[] {
  const names = new Set<string>();
  names.add(harnessInstructionFileName(harness));
  for (const entryName of topLevelEntryNames(sourceRoot)) {
    names.add(entryName);
  }
  if (hasSkillsSource) {
    names.add(SKILLS_DST_DIR);
  }
  return uniqueSorted([...names]);
}

function harnessDirJobs(harnesses: readonly HarnessPlan[]): Job[] {
  return harnesses.map((plan) => {
    const endpointTemplatePaths = cliProxyEndpointTemplatePaths(plan);
    return {
      src: plan.sourceRoot,
      dst: plan.root,
      kind: "Dir",
      scope: "Children",
      ...(endpointTemplatePaths.length === 0 ? {} : { preservePaths: endpointTemplatePaths }),
    };
  });
}

function skillsJobs(syncEnv: SyncEnv, harnesses: readonly HarnessPlan[]): Job[] {
  const skillsSource = join(syncEnv.skillsHome, SKILLS_SOURCE_SUBDIR);
  return harnesses.map((plan) => ({
    src: skillsSource,
    dst: join(plan.root, SKILLS_DST_DIR),
    kind: "Dir",
    scope: "Tree",
  }));
}

function skillsSourceExists(syncEnv: SyncEnv): boolean {
  return isDirectory(join(syncEnv.skillsHome, SKILLS_SOURCE_SUBDIR));
}

function instructionJobs(syncEnv: SyncEnv, harnesses: readonly HarnessPlan[]): Job[] {
  return harnesses.map((plan) => ({
    src: join(syncEnv.ssotHome, SOURCE_AGENT_FILE),
    dst: plan.instructionTarget,
    kind: "File",
  }));
}

const CLIPROXY_ENDPOINT_TEMPLATE_PATHS: Partial<Record<Harness["id"], readonly string[]>> = {
  codex: ["config.toml"],
  grok: ["config.toml"],
  opencode: ["opencode.jsonc", join("plugins", "cliproxy.ts")],
  pi: [join("extensions", "cliproxy", "index.ts")],
  omp: ["models.yml"],
};

function configJobs(
  syncEnv: SyncEnv,
  harnesses: readonly HarnessPlan[],
  deployment: CliProxyDeployment,
  gatewayHost: boolean,
): Job[] {
  const endpointTargets = harnesses.flatMap((plan): CliProxyEndpointTarget[] => {
    const relativePaths = cliProxyEndpointTemplatePaths(plan);
    return relativePaths.map((relativePath) => {
      const sourcePath = join(plan.sourceRoot, relativePath);
      if (plan.harness.id === "codex" && relativePath === "config.toml") {
        return {
          src: sourcePath,
          dst: join(plan.root, relativePath),
          preserveTopLevels: ["hooks.state", "projects"] as const,
        };
      }
      return { src: sourcePath, dst: join(plan.root, relativePath) };
    });
  });
  return [
    {
      kind: "CliProxyReadiness",
      deployment,
      gatewayHost,
    },
    {
      src: join(syncEnv.ssotHome, "tools", "mcporter", "mcporter.jsonc"),
      dst: join(syncEnv.mcporterHome, "mcporter.json"),
      kind: "File",
    },
    {
      src: join(syncEnv.ssotHome, "tools", "summarize", "config.json"),
      dst: join(syncEnv.summarizeHome, "config.json"),
      kind: "File",
    },
    {
      src: join(syncEnv.ssotHome, CLI_PROXY_SOURCE_DIR, "config.yaml.tmpl"),
      dst: join(syncEnv.home, ".cli-proxy-api", "config.yaml"),
      kind: "CliProxyConfig",
      secretsPath: join(syncEnv.home, ".config", "agents", "secrets.local.json"),
      deployment,
      gatewayHost,
      cacheRoot: join(syncEnv.home, ".cache", "agents", "model-catalog"),
      runtimeRoot: syncEnv.runtimeHome,
    },
    ...(gatewayHost
      ? [
          {
            src: join(syncEnv.ssotHome, CLI_PROXY_SOURCE_DIR, "panel.html"),
            dst: join(syncEnv.home, ".cli-proxy-api", "static", "management.html"),
            kind: "File",
          } satisfies Job,
        ]
      : []),
    {
      kind: "CliProxyEndpointTemplates",
      targets: endpointTargets,
      deployment,
    },
  ];
}

function cliProxyEndpointTemplatePaths(plan: HarnessPlan): readonly string[] {
  const relativePaths = CLIPROXY_ENDPOINT_TEMPLATE_PATHS[plan.harness.id];
  if (relativePaths === undefined) {
    return [];
  }
  return relativePaths.filter((relativePath) => {
    const sourcePath = join(plan.sourceRoot, relativePath);
    return (
      fs.existsSync(sourcePath) &&
      fs.readFileSync(sourcePath, "utf8").includes(CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER)
    );
  });
}

function buildHookPlans(
  syncEnv: SyncEnv,
  harness: Harness,
  root: string,
  sourceRoot: string,
): SyncHookPlan[] {
  return harness.hooks.map((hook) => {
    switch (hook.kind) {
      case "PackageBootstrap":
        return {
          kind: hook.kind,
          harness,
          manifestPath: join(sourceRoot, hook.manifestFile),
          runtimeSettingsPath: join(root, hook.settingsFile),
          cacheRoot: join(syncEnv.home, hook.cacheSubdir ?? ".local/share/agents/pi-packages"),
          timeoutMs: syncEnv.installTimeoutMs,
        };
      case "ExtensionDeps":
        return {
          kind: hook.kind,
          harness,
          jobRoot: root,
          root: join(root, hook.rootDir),
          sourceRoot: join(sourceRoot, hook.rootDir),
          relativeRoot: hook.rootDir === "." ? "" : hook.rootDir,
          statePath: extensionHookStatePath(syncEnv.managedStateHome, harness),
          timeoutMs: syncEnv.installTimeoutMs,
        };
      default:
        return assertNever(hook);
    }
  });
}

const extensionHookStatePath = (managedStateHome: string, harness: Harness): string =>
  join(managedStateHome, `${harness.sourceName}.extension-deps.json`);

function dirEntryNames(root: string): string[] {
  if (!isDirectory(root)) {
    return [];
  }

  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(root, { withFileTypes: true });
  } catch (error) {
    throw new Error(`read ${root} (${panicMessage(error)})`, { cause: error });
  }

  return uniqueSorted(entries.map((entry) => entry.name));
}

const uniqueSorted = (names: readonly string[]): string[] => [...new Set(names)].toSorted();

function isDirectory(root: string): boolean {
  try {
    return fs.statSync(root).isDirectory();
  } catch {
    return false;
  }
}

const isTopLevel = (entryName: string): boolean =>
  entryName.length > 0 &&
  !posix.isAbsolute(entryName) &&
  !entryName.includes("/") &&
  entryName !== "." &&
  entryName !== "..";

export const isSafeManagedEntryName = (entryName: string): boolean => isTopLevel(entryName);
