import * as fs from "node:fs";
import path from "node:path";

import { Effect } from "effect";

import {
  installInferredImportPackages as installInferredImportPackagesImpl,
  installPackageDeps,
  runPackageBuild,
} from "./packages/process.ts";
import {
  cloneAttemptsForTests as cloneAttemptsForTestsImpl,
  clonePackage,
  commandForTests as commandForTestsImpl,
  githubSlugForTests as githubSlugForTestsImpl,
  packageCacheDir as packageCacheDirImpl,
  replaceDirAtomically,
  rmEntry,
  stagingDirFor,
} from "./packages/source.ts";
import {
  packageHasBuildScript,
  packageIsHealthy,
  validatePackageForTests as validatePackageForTestsImpl,
} from "./packages/validate.ts";

const PACKAGE_SOURCE_FILE = "packages.json";
const PACKAGE_CACHE_SUBDIR = ".local/share/agents/pi-packages";

export interface PackageManifest {
  readonly packages: string[];
}

export interface HarnessLike {
  readonly id?: unknown;
  readonly sourceName?: string;
  readonly source_name?: string;
  readonly home?: string;
  readonly runtimeSubdir?: string | null;
  readonly runtime_subdir?: string | null;
  sourceRoot?(toolsHome: string): string;
  root?(): string;
}

export interface SyncEnvLike {
  readonly home: string;
  readonly toolsHome?: string;
  readonly tools_home?: string;
  readonly installTimeout?: number;
  readonly installTimeoutMs?: number;
  readonly install_timeout?: number;
  readonly harnesses?: readonly HarnessLike[];
  harness?(id: unknown): HarnessLike | undefined;
}

function err(message: string): void {
  console.error(`sync: ${message}`);
}

function getToolsHome(syncEnv: SyncEnvLike): string {
  return syncEnv.toolsHome ?? syncEnv.tools_home ?? path.join(syncEnv.home, ".config", "agents", "tools");
}

function getHarnessSourceName(harness: HarnessLike, fallback = "pi"): string {
  return harness.sourceName ?? harness.source_name ?? fallback;
}

function getHarnessRoot(harness: HarnessLike, fallbackHome: string): string {
  if (typeof harness.root === "function") {
    return harness.root();
  }

  const home = harness.home ?? fallbackHome;
  const runtimeSubdir = harness.runtimeSubdir ?? harness.runtime_subdir;
  return runtimeSubdir ? path.join(home, runtimeSubdir) : home;
}

function getHarnessSourceRoot(harness: HarnessLike, toolsHome: string, sourceName: string): string {
  if (typeof harness.sourceRoot === "function") {
    return harness.sourceRoot(toolsHome);
  }

  const runtimeSubdir = harness.runtimeSubdir ?? harness.runtime_subdir;
  const base = path.join(toolsHome, sourceName);
  return runtimeSubdir ? path.join(base, runtimeSubdir) : base;
}

function getPiHarness(syncEnv: SyncEnvLike): HarnessLike | undefined {
  if (typeof syncEnv.harness === "function") {
    const candidates = [syncEnv.harness("Pi"), syncEnv.harness("pi"), syncEnv.harness("PI")];
    for (const candidate of candidates) {
      if (candidate) {
        return candidate;
      }
    }
  }

  for (const harness of syncEnv.harnesses ?? []) {
    if (getHarnessSourceName(harness, "") === "pi") {
      return harness;
    }
    if (String(harness.id ?? "").toLowerCase() === "pi") {
      return harness;
    }
  }
  return undefined;
}

export function packageCacheDir(cacheRoot: string, source: string): string {
  return packageCacheDirImpl(cacheRoot, source);
}

export function githubSlugForTests(source: string): string | null {
  return githubSlugForTestsImpl(source);
}

export function commandForTests(source: string, targetDir: string): string[] {
  return commandForTestsImpl(source, targetDir);
}

export function cloneAttemptsForTests(
  source: string,
  targetDir: string,
  ghAvailable: boolean,
  outcomes: readonly boolean[],
): Promise<[boolean, string[][]]> {
  return cloneAttemptsForTestsImpl(source, targetDir, ghAvailable, outcomes);
}

export function validatePackageForTests(dir: string): boolean {
  return validatePackageForTestsImpl(dir);
}

export function readPackageManifest(filePath: string): PackageManifest {
  let content: string;
  try {
    content = fs.readFileSync(filePath, "utf8");
  } catch (error) {
    if (isNotFound(error)) {
      return { packages: [] };
    }
    throw new Error(`${filePath} (${String(error)})`);
  }

  let value: unknown;
  try {
    value = JSON.parse(content) as unknown;
  } catch (error) {
    throw new Error(`invalid JSON in ${filePath}: ${String(error)}`);
  }

  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${filePath} must contain a JSON object`);
  }
  const object = value as Record<string, unknown>;
  const packagesValue = object.packages;
  if (packagesValue === undefined) {
    throw new Error(`${filePath} missing "packages" array`);
  }
  if (!Array.isArray(packagesValue)) {
    throw new Error(`${filePath} field "packages" must be an array`);
  }

  const seen = new Set<string>();
  const packages: string[] = [];
  for (const entry of packagesValue) {
    if (typeof entry !== "string") {
      throw new Error(`${filePath} package entries must be strings`);
    }
    const source = entry.trim();
    if (source.length === 0) {
      throw new Error(`${filePath} package entries must not be empty`);
    }
    if (!seen.has(source)) {
      seen.add(source);
      packages.push(source);
    }
  }

  return { packages };
}

export function patchRuntimeSettings(filePath: string, packagePaths: readonly string[]): void {
  let current = "{}";
  try {
    current = fs.readFileSync(filePath, "utf8");
  } catch (error) {
    if (!isNotFound(error)) {
      throw new Error(`read ${filePath} (${String(error)})`);
    }
  }

  let value: unknown;
  try {
    value = JSON.parse(current) as unknown;
  } catch (error) {
    throw new Error(`parse ${filePath} (${String(error)})`);
  }

  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    value = {};
  }

  (value as Record<string, unknown>).packages = packagePaths.map((packagePath) => packagePath.toString());

  const parent = path.dirname(filePath);
  if (parent.length > 0) {
    fs.mkdirSync(parent, { recursive: true });
  }

  try {
    fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`);
  } catch (error) {
    throw new Error(`write ${filePath} (${String(error)})`);
  }
}

async function ensurePackage(source: string, cacheRoot: string, timeoutMs: number): Promise<string> {
  const finalDir = packageCacheDir(cacheRoot, source);
  if (packageIsHealthy(finalDir)) {
    return finalDir;
  }

  fs.mkdirSync(cacheRoot, { recursive: true });

  const stagingDir = stagingDirFor(finalDir);
  rmEntry(stagingDir);
  fs.mkdirSync(path.dirname(stagingDir), { recursive: true });

  try {
    if (!(await clonePackage(source, stagingDir, timeoutMs))) {
      throw new Error("clone failed");
    }
    if (!(await Effect.runPromise(installPackageDeps(stagingDir, timeoutMs)))) {
      throw new Error("dependency install failed");
    }

    let healthy = packageIsHealthy(stagingDir);
    if (!healthy && packageHasBuildScript(stagingDir)) {
      if (!(await Effect.runPromise(runPackageBuild(stagingDir, timeoutMs)))) {
        throw new Error("build failed");
      }
      if (!(await Effect.runPromise(installInferredImportPackagesImpl(stagingDir, timeoutMs)))) {
        throw new Error("install inferred packages after build failed");
      }
      healthy = packageIsHealthy(stagingDir);
    }

    if (!healthy) {
      throw new Error("package resources failed validation");
    }

    await replaceDirAtomically(stagingDir, finalDir);
    return finalDir;
  } catch (error) {
    rmEntry(stagingDir);
    throw error;
  }
}

export async function bootstrapPackages(syncEnv: SyncEnvLike): Promise<boolean> {
  const toolsHome = getToolsHome(syncEnv);
  const piHarness = getPiHarness(syncEnv);
  const manifestPath = piHarness
    ? path.join(getHarnessSourceRoot(piHarness, toolsHome, "pi"), PACKAGE_SOURCE_FILE)
    : path.join(toolsHome, "pi", "agent", PACKAGE_SOURCE_FILE);
  const runtimeSettingsPath = piHarness
    ? path.join(getHarnessRoot(piHarness, path.join(syncEnv.home, ".pi", "agent")), "settings.json")
    : path.join(syncEnv.home, ".pi", "agent", "settings.json");
  const cacheRoot = path.join(syncEnv.home, PACKAGE_CACHE_SUBDIR);

  let manifest: PackageManifest;
  try {
    manifest = readPackageManifest(manifestPath);
  } catch (error) {
    err(`package bootstrap failed: ${String(error instanceof Error ? error.message : error)}`);
    return false;
  }

  const installedPaths: string[] = [];
  let success = true;
  for (const source of manifest.packages) {
    try {
      installedPaths.push(
        await ensurePackage(
          source,
          cacheRoot,
          syncEnv.installTimeoutMs ?? syncEnv.installTimeout ?? syncEnv.install_timeout ?? 120_000,
        ),
      );
    } catch (error) {
      err(`package bootstrap failed for ${source}: ${String(error instanceof Error ? error.message : error)}`);
      success = false;
    }
  }

  try {
    patchRuntimeSettings(runtimeSettingsPath, installedPaths);
  } catch (error) {
    err(`package settings patch failed: ${String(error instanceof Error ? error.message : error)}`);
    success = false;
  }

  return success;
}

export async function installInferredImportPackages(
  dir: string,
  timeoutMs: number,
): Promise<boolean> {
  return Effect.runPromise(installInferredImportPackagesImpl(dir, timeoutMs));
}

export const bootstrapPackagesEffect = (syncEnv: SyncEnvLike) =>
  Effect.tryPromise({
    try: () => bootstrapPackages(syncEnv),
    catch: (error) => error as Error,
  });

export { packageHasBuildScript, packageIsHealthy };

function isNotFound(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code?: unknown }).code === "ENOENT"
  );
}
