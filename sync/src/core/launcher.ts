import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { releaseSyncLock, type SyncLock, tryAcquireSyncLock } from "@runtime/lock.ts";
import type { Harness, SyncEnv } from "./harness.ts";

const DEFAULT_LAUNCH_TIMEOUT_MS = 120_000;
const VERSION_PATTERN = /^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/;
const COMPONENT_PATTERN = /^[A-Za-z0-9._-]+$/;
const PACKAGE_PATTERN = /^(?:@[A-Za-z0-9._~-]+\/)?[A-Za-z0-9._~-]+$/;

export interface NpmPackageSpec {
  readonly tool: string;
  readonly package: string;
  readonly bin: string;
  readonly distTag?: string;
  readonly smokeCheck?: string;
  readonly env?: Record<string, string> | undefined;
}

export interface NpmCacheLayout {
  readonly toolCache: string;
  readonly versionsDir: string;
  readonly currentLink: string;
  readonly previousLink: string;
  readonly lockFile: string;
}

export interface LauncherProcessResult {
  readonly exitCode: number;
  readonly stdout: string;
  readonly stderr: string;
  readonly timedOut?: boolean;
}

export interface LauncherRuntime {
  readonly resolveVersion?: (
    packageName: string,
    distTag: string,
    timeoutMs: number,
  ) => Promise<string>;
  readonly run?: (
    command: readonly string[],
    cwd: string | undefined,
    timeoutMs: number | undefined,
    stdio: "pipe" | "inherit",
  ) => Promise<LauncherProcessResult>;
}

export interface PreparePackageOptions {
  readonly home: string;
  readonly cacheHome?: string;
  readonly timeoutMs?: number;
  readonly runtime?: LauncherRuntime;
}

export interface PreparedNpmPackage {
  readonly layout: NpmCacheLayout;
  readonly resolvedVersion: string;
  readonly currentBin: string;
}

export function npmCacheLayout(
  home: string,
  spec: Pick<NpmPackageSpec, "tool" | "package">,
  cacheHome = process.env["XDG_CACHE_HOME"] || path.join(home, ".cache"),
): NpmCacheLayout {
  requireComponent(spec.tool, "tool");
  const toolCache = path.join(cacheHome, "npm-tools", spec.tool);
  const packageKey = createHash("sha256").update(spec.package).digest("hex").slice(0, 16);
  const packageCache = path.join(toolCache, "packages", packageKey);
  return {
    toolCache,
    versionsDir: path.join(packageCache, "versions"),
    currentLink: path.join(packageCache, "current"),
    previousLink: path.join(packageCache, "previous"),
    lockFile: path.join(toolCache, "lock"),
  };
}

export async function prepareNpmPackage(
  spec: NpmPackageSpec,
  options: PreparePackageOptions,
): Promise<PreparedNpmPackage> {
  validateSpec(spec);
  const timeoutMs = options.timeoutMs ?? DEFAULT_LAUNCH_TIMEOUT_MS;
  const layout = npmCacheLayout(options.home, spec, options.cacheHome);
  fs.mkdirSync(layout.versionsDir, { recursive: true });

  const lock = await acquireCacheLock(layout, timeoutMs);
  try {
    const runtime = options.runtime ?? {};
    const distTag = spec.distTag ?? "latest";
    const cached = currentCachedPackage(layout, spec);
    let resolvedVersion: string;
    try {
      const resolve =
        runtime.resolveVersion ??
        ((packageName: string, tag: string, timeout: number) =>
          resolveVersion(packageName, tag, timeout));
      resolvedVersion = validateResolvedVersion(await resolve(spec.package, distTag, timeoutMs));
    } catch (error) {
      if (!cached) {
        throw error;
      }
      warnUsingCachedPackage(spec, cached.version, error);
      return {
        layout,
        resolvedVersion: cached.version,
        currentBin: cached.currentBin,
      };
    }
    const versionDir = path.join(layout.versionsDir, resolvedVersion);
    const stagedBin = packageBinPath(versionDir, spec.bin);
    let stageDir: string | undefined;

    try {
      if (isExecutable(stagedBin) && !installedPackageMatches(versionDir, spec, resolvedVersion)) {
        throw new Error(`cached package identity mismatch: ${resolvedVersion}`);
      }
      if (!isExecutable(stagedBin)) {
        if (fs.existsSync(versionDir)) {
          throw new Error(`cached package is incomplete: ${resolvedVersion}`);
        }

        stageDir = fs.mkdtempSync(path.join(layout.versionsDir, ".stage."));
        const install = await (runtime.run ?? runLauncherProcess)(
          [
            "npm",
            "install",
            "--prefix",
            stageDir,
            "--no-save",
            "--no-package-lock",
            "--no-audit",
            "--no-fund",
            "--loglevel=error",
            `${spec.package}@${resolvedVersion}`,
          ],
          undefined,
          timeoutMs,
          "pipe",
        );
        if (install.timedOut || install.exitCode !== 0) {
          throw new Error(`npm install failed: ${detailFromResult(install)}`);
        }

        const installedBin = packageBinPath(stageDir, spec.bin);
        if (!isExecutable(installedBin)) {
          throw new Error(`installed package has no executable bin: ${spec.bin}`);
        }
        if (!installedPackageMatches(stageDir, spec, resolvedVersion)) {
          throw new Error(
            `installed package identity mismatch: ${spec.package}@${resolvedVersion}`,
          );
        }
        if ((spec.smokeCheck ?? "--version") !== "-") {
          const smoke = await (runtime.run ?? runLauncherProcess)(
            [installedBin, spec.smokeCheck ?? "--version"],
            stageDir,
            timeoutMs,
            "pipe",
          );
          if (smoke.timedOut || smoke.exitCode !== 0) {
            throw new Error(`installed package smoke check failed: ${detailFromResult(smoke)}`);
          }
        }

        fs.renameSync(stageDir, versionDir);
        stageDir = undefined;
      }

      updateCurrentAndPrevious(layout, resolvedVersion);
      pruneVersions(layout);

      const currentBin = packageBinPath(layout.currentLink, spec.bin);
      if (!isExecutable(currentBin)) {
        throw new Error(`current package has no executable bin: ${spec.bin}`);
      }

      return { layout, resolvedVersion, currentBin };
    } catch (error) {
      const fallback = currentCachedPackage(layout, spec);
      if (!fallback) {
        throw error;
      }
      warnUsingCachedPackage(spec, fallback.version, error);
      return {
        layout,
        resolvedVersion: fallback.version,
        currentBin: fallback.currentBin,
      };
    } finally {
      if (stageDir) {
        fs.rmSync(stageDir, { recursive: true, force: true });
      }
    }
  } finally {
    releaseSyncLock(lock);
  }
}

export async function launchNpmPackage(
  syncEnv: Pick<SyncEnv, "home" | "installTimeoutMs">,
  spec: NpmPackageSpec,
  args: readonly string[],
  runtime: LauncherRuntime = {},
): Promise<number> {
  const prepared = await prepareNpmPackage(spec, {
    home: syncEnv.home,
    timeoutMs: syncEnv.installTimeoutMs,
    runtime,
  });
  const result = await (runtime.run ?? runLauncherProcess)(
    [prepared.currentBin, ...args],
    undefined,
    undefined,
    "inherit",
    spec.env,
  );
  if (result.timedOut) {
    console.error(`sync: ${spec.tool} launch timed out`);
    return 124;
  }
  return result.exitCode;
}

export function launchHarness(
  syncEnv: SyncEnv,
  harness: Harness,
  args: readonly string[],
  runtime: LauncherRuntime = {},
): Promise<number> {
  return launchNpmPackage(
    syncEnv,
    {
      tool: harness.sourceName,
      package: harness.launcher.package,
      bin: harness.launcher.bin,
      distTag: harness.launcher.distTag,
      smokeCheck: harness.launcher.smokeCheck,
      ...(harness.launcher.env === undefined ? {} : { env: harness.launcher.env }),
    },
    args,
    runtime,
  );
}

async function resolveVersion(
  packageName: string,
  distTag: string,
  timeoutMs: number,
): Promise<string> {
  const result = await runLauncherProcess(
    ["npm", "view", `${packageName}@${distTag}`, "version"],
    undefined,
    timeoutMs,
    "pipe",
  );
  if (result.timedOut || result.exitCode !== 0) {
    throw new Error(`could not resolve ${packageName}@${distTag}`);
  }
  return result.stdout.replace(/[\r\n]+/g, "").trim();
}

async function runLauncherProcess(
  command: readonly string[],
  cwd: string | undefined,
  timeoutMs: number | undefined,
  stdio: "pipe" | "inherit",
  env?: Record<string, string>,
): Promise<LauncherProcessResult> {
  const signal = timeoutMs === undefined ? undefined : AbortSignal.timeout(timeoutMs);
  let subprocess:
    | Bun.Subprocess<"pipe", "pipe", "inherit">
    | Bun.Subprocess<"inherit", "inherit", "inherit">;
  try {
    subprocess = Bun.spawn([...command], {
      ...(cwd === undefined ? {} : { cwd }),
      env: { ...process.env, ...env },
      killSignal: "SIGKILL",
      ...(signal ? { signal } : {}),
      stdin: stdio === "pipe" ? "ignore" : "inherit",
      stdout: stdio,
      stderr: stdio,
    });
  } catch (error) {
    return {
      exitCode: 127,
      stdout: "",
      stderr: String(error),
    };
  }

  if (stdio === "inherit") {
    const exitCode = await subprocess.exited;
    return { exitCode, stdout: "", stderr: "", timedOut: signal?.aborted ?? false };
  }

  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(subprocess.stdout).text().catch(() => ""),
    new Response(subprocess.stderr).text().catch(() => ""),
    subprocess.exited,
  ]);
  return { exitCode, stdout, stderr, timedOut: signal?.aborted ?? false };
}

async function acquireCacheLock(layout: NpmCacheLayout, timeoutMs: number): Promise<SyncLock> {
  const startedAt = Date.now();
  while (true) {
    const lock = tryAcquireSyncLock(layout.toolCache, layout.lockFile);
    if (lock) {
      return lock;
    }
    if (Date.now() - startedAt >= timeoutMs) {
      throw new Error(`timed out waiting for npm cache lock: ${layout.lockFile}`);
    }
    await Bun.sleep(25);
  }
}

function updateCurrentAndPrevious(layout: NpmCacheLayout, version: string): void {
  const expectedTarget = path.relative(
    path.dirname(layout.currentLink),
    path.join(layout.versionsDir, version),
  );
  const currentTarget = readLinkTarget(layout.currentLink);
  if (currentTarget === expectedTarget) {
    return;
  }
  if (currentTarget) {
    replaceLink(layout.previousLink, currentTarget);
  }
  replaceLink(layout.currentLink, expectedTarget);
}

function replaceLink(linkPath: string, target: string): void {
  const tempPath = `${linkPath}.${process.pid}.tmp`;
  fs.rmSync(tempPath, { recursive: true, force: true });
  fs.symlinkSync(target, tempPath, "dir");
  fs.rmSync(linkPath, { recursive: true, force: true });
  fs.renameSync(tempPath, linkPath);
}

function pruneVersions(layout: NpmCacheLayout): void {
  const keep = new Set<string>();
  for (const linkPath of [layout.currentLink, layout.previousLink]) {
    const target = readLinkTarget(linkPath);
    if (target) {
      keep.add(path.basename(target));
    }
  }
  for (const entry of fs.readdirSync(layout.versionsDir, { withFileTypes: true })) {
    if (entry.name.startsWith(".stage.")) {
      continue;
    }
    if (keep.has(entry.name)) {
      continue;
    }
    fs.rmSync(path.join(layout.versionsDir, entry.name), {
      recursive: true,
      force: true,
    });
  }
}

function readLinkTarget(linkPath: string): string | undefined {
  try {
    const metadata = fs.lstatSync(linkPath);
    if (!metadata.isSymbolicLink()) {
      if (metadata.isFile() || metadata.isDirectory()) {
        throw new Error(`cache entry is not a symlink: ${linkPath}`);
      }
      return undefined;
    }
    return fs.readlinkSync(linkPath);
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("cache entry")) {
      throw error;
    }
    return undefined;
  }
}

const packageBinPath = (root: string, bin: string): string =>
  path.join(root, "node_modules", ".bin", bin);

function validateSpec(spec: NpmPackageSpec): void {
  requireComponent(spec.tool, "tool");
  requireComponent(spec.bin, "bin");
  requireComponent(spec.distTag ?? "latest", "dist-tag");
  if (!PACKAGE_PATTERN.test(spec.package)) {
    throw new Error(`invalid package: ${spec.package}`);
  }
  if (spec.smokeCheck !== undefined && !spec.smokeCheck.trim() && spec.smokeCheck !== "-") {
    throw new Error("missing smoke check");
  }
}

function validateResolvedVersion(version: string): string {
  if (!VERSION_PATTERN.test(version)) {
    throw new Error(`invalid resolved version: ${version}`);
  }
  return version;
}

function currentCachedPackage(
  layout: NpmCacheLayout,
  spec: NpmPackageSpec,
): { readonly version: string; readonly currentBin: string } | undefined {
  try {
    const target = readLinkTarget(layout.currentLink);
    if (!target) {
      return undefined;
    }
    const currentBin = packageBinPath(layout.currentLink, spec.bin);
    if (!isExecutable(currentBin)) {
      return undefined;
    }
    const version = path.basename(target);
    if (!installedPackageMatches(layout.currentLink, spec, version)) {
      return undefined;
    }
    return { version, currentBin };
  } catch {
    return undefined;
  }
}

function warnUsingCachedPackage(spec: NpmPackageSpec, version: string, error: unknown): void {
  console.error(
    `sync: warning: latest ${spec.package}@${spec.distTag ?? "latest"} unavailable (${detailFromError(error)}); using cached ${spec.tool}@${version}`,
  );
}

function detailFromError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function installedPackageMatches(
  root: string,
  spec: Pick<NpmPackageSpec, "package">,
  version: string,
): boolean {
  try {
    const manifestPath = path.join(
      root,
      "node_modules",
      ...spec.package.split("/"),
      "package.json",
    );
    const manifest: unknown = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    return (
      typeof manifest === "object" &&
      manifest !== null &&
      "name" in manifest &&
      manifest.name === spec.package &&
      "version" in manifest &&
      manifest.version === version
    );
  } catch {
    return false;
  }
}

function requireComponent(value: string, label: string): void {
  if (!value || !COMPONENT_PATTERN.test(value) || value === "." || value === "..") {
    throw new Error(`invalid ${label}: ${value}`);
  }
}

function isExecutable(targetPath: string): boolean {
  try {
    const metadata = fs.statSync(targetPath);
    return metadata.isFile() && (metadata.mode & 0o111) !== 0;
  } catch {
    return false;
  }
}

function detailFromResult(result: LauncherProcessResult): string {
  return result.stderr.trim() || result.stdout.trim() || "unknown error";
}
