import crypto from "node:crypto";
import fs from "node:fs";
import { basename, dirname, join, relative } from "node:path";
import { assertNever, err, panicMessage, warn } from "@runtime/errors.ts";
import { isSymlink, rmEntry, syncManagedChildren, syncManagedTree } from "@runtime/fs.ts";
import { runProcess } from "@runtime/process.ts";
import { syncCliProxyConfig } from "./cliproxy-config.ts";
import { isCliProxyTargetReady, publishCliProxyEndpointTemplates } from "./cliproxy-deployment.ts";
import type { Job, SyncRuntimeInstallJob } from "./plan.ts";
import { syncSecretTemplate } from "./secret-template.ts";

type SourceContentCache = Map<string, { readonly metadata: fs.Stats; readonly content: Buffer }>;

export type { Job, JobKind } from "./plan.ts";

interface JobRunState {
  cliProxyTargetReady: boolean | undefined;
}

export async function runJobsWithPreserve(
  jobs: readonly Job[],
  preservePathsByDst: ReadonlyMap<string, readonly string[]> = new Map(),
): Promise<boolean> {
  const sourceContentCache: SourceContentCache = new Map();
  const state: JobRunState = { cliProxyTargetReady: undefined };
  for (const job of jobs) {
    if (!(await runJob(job, preservePathsByDst, sourceContentCache, state))) {
      return false;
    }
  }
  return true;
}

async function runJob(
  job: Job,
  preservePathsByDst: ReadonlyMap<string, readonly string[]>,
  sourceContentCache: SourceContentCache,
  state: JobRunState,
): Promise<boolean> {
  try {
    switch (job.kind) {
      case "Dir": {
        const preservePaths = [
          ...(preservePathsByDst.get(job.dst) ?? []),
          ...(job.preservePaths ?? []),
        ];
        return job.scope === "Children"
          ? syncDirInto(job.src, job.dst, preservePaths, sourceContentCache)
          : syncManagedDir(job.src, job.dst, preservePaths, sourceContentCache);
      }
      case "File":
        return syncItem(job.src, job.dst);
      case "SecretTemplate":
        if (!fs.existsSync(job.src)) {
          err(`missing source: ${job.src}`);
          return true;
        }
        if (!fs.existsSync(job.secretsPath)) {
          warn(`missing local secrets ${job.secretsPath}; skipping ${job.dst}`);
          return true;
        }
        syncSecretTemplate(job.src, job.dst, job.secretsPath);
        return true;
      case "CliProxyReadiness": {
        if (job.gatewayHost) {
          return true;
        }
        state.cliProxyTargetReady = await isCliProxyTargetReady(job.deployment);
        if (!state.cliProxyTargetReady) {
          warn("CLIProxyAPI endpoint is not ready; preserving existing client artifacts");
        }
        return true;
      }
      case "CliProxyEndpointTemplates": {
        if (state.cliProxyTargetReady === false) {
          return true;
        }
        const publication = await publishCliProxyEndpointTemplates(job.targets, job.deployment, {
          skipReadiness: state.cliProxyTargetReady === true,
        });
        if (publication === "skipped" && job.targets.length > 0) {
          warn("CLIProxyAPI endpoint is not ready; preserving existing harness endpoints");
        }
        return true;
      }
      case "CliProxyConfig":
        if (state.cliProxyTargetReady === false || job.gatewayHost === false) {
          return true;
        }
        if (!fs.existsSync(job.src)) {
          err(`missing source: ${job.src}`);
          return true;
        }
        if (!fs.existsSync(job.secretsPath)) {
          warn(`missing local secrets ${job.secretsPath}; skipping ${job.dst}`);
          return true;
        }
        await syncCliProxyConfig(job.src, job.dst, job.secretsPath, job.deployment);
        return true;
      case "SyncRuntimeInstall":
        return await runSyncRuntimeInstallJob(job);
      default:
        return assertNever(job);
    }
  } catch (error) {
    err(`unexpected error in ${job.kind}: ${panicMessage(error)}`);
    return false;
  }
}

async function runSyncRuntimeInstallJob(job: SyncRuntimeInstallJob): Promise<boolean> {
  const requiredPaths = validateRequiredSources(job.sourceRoot);
  if (requiredPaths === false) {
    return false;
  }

  fs.mkdirSync(job.releasesRoot, { recursive: true });

  const releaseId = computeRuntimeReleaseId(requiredPaths);
  const releaseDir = join(job.releasesRoot, releaseId);
  if (isCompleteRelease(releaseDir)) {
    return publishAndPrune(job, releaseDir);
  }

  const stage = createStage(job.releasesRoot);
  try {
    copyRuntimeInputs(requiredPaths, stage, new Map());
    const install = await runProcess(["bun", "install", "--frozen-lockfile", "--production"], {
      cwd: stage,
      timeoutMs: Math.max(job.timeoutMs, 1_000),
    });
    if (install.timedOut || install.exitCode !== 0) {
      const detail = install.stderr.trim() || install.stdout.trim() || "unknown error";
      throw new Error(`runtime dependency install failed: ${detail}`);
    }
    if (!isCompleteRelease(stage)) {
      throw new Error("runtime install did not produce a complete release");
    }

    if (fs.existsSync(releaseDir)) {
      if (isCompleteRelease(releaseDir)) {
        fs.rmSync(stage, { recursive: true, force: true });
        return publishAndPrune(job, releaseDir);
      }
      fs.rmSync(releaseDir, { recursive: true, force: true });
    }
    fs.renameSync(stage, releaseDir);
  } catch (error) {
    err(`runtime install failed: ${panicMessage(error)}`);
    try {
      fs.rmSync(stage, { recursive: true, force: true });
    } catch {
      // ignore
    }
    return false;
  }
  return publishAndPrune(job, releaseDir);
}

function validateRequiredSources(sourceRoot: string): RequiredPaths | false {
  const srcDir = join(sourceRoot, "src");
  const packageJson = join(sourceRoot, "package.json");
  const tsconfigJson = join(sourceRoot, "tsconfig.json");
  const bunLock = join(sourceRoot, "bun.lock");
  if (!isRegularReadable(srcDir, "src/", "directory")) {
    return false;
  }
  if (!isRegularReadable(packageJson, "package.json", "file")) {
    return false;
  }
  if (!isRegularReadable(tsconfigJson, "tsconfig.json", "file")) {
    return false;
  }
  if (!isRegularReadable(bunLock, "bun.lock", "file")) {
    return false;
  }
  return { srcDir, packageJson, tsconfigJson, bunLock };
}

interface RequiredPaths {
  readonly srcDir: string;
  readonly packageJson: string;
  readonly tsconfigJson: string;
  readonly bunLock: string;
}

function isRegularReadable(targetPath: string, label: string, kind: "directory" | "file"): boolean {
  try {
    const metadata = fs.lstatSync(targetPath);
    if (metadata.isSymbolicLink()) {
      err(`runtime source ${label} is a symlink: ${targetPath}`);
      return false;
    }
    if (kind === "directory") {
      if (!metadata.isDirectory()) {
        err(`runtime source ${label} is not a directory: ${targetPath}`);
        return false;
      }
      fs.accessSync(targetPath, fs.constants.R_OK | fs.constants.X_OK);
      return true;
    }
    if (!metadata.isFile()) {
      err(`runtime source ${label} is not a regular file: ${targetPath}`);
      return false;
    }
    fs.accessSync(targetPath, fs.constants.R_OK);
    return true;
  } catch (error) {
    err(`missing or unreadable runtime source ${label}: ${targetPath} (${panicMessage(error)})`);
    return false;
  }
}

function computeRuntimeReleaseId(paths: RequiredPaths): string {
  const hasher = crypto.createHash("sha256");
  hashDirectoryInto(paths.srcDir, hasher);
  for (const file of [paths.packageJson, paths.tsconfigJson, paths.bunLock]) {
    hasher.update(fs.readFileSync(file));
  }
  return hasher.digest("hex");
}

function hashDirectoryInto(root: string, hasher: crypto.Hash, prefix: string = ""): void {
  for (const entry of fs
    .readdirSync(root, { withFileTypes: true })
    .toSorted((left, right) => left.name.localeCompare(right.name))) {
    const absolute = join(root, entry.name);
    const relativePath = prefix.length === 0 ? entry.name : `${prefix}/${entry.name}`;
    if (entry.isSymbolicLink()) {
      const targetMetadata = fs.statSync(absolute);
      if (targetMetadata.isDirectory()) {
        throw new Error(`refusing source directory symlink: ${absolute}`);
      }
      hasher.update(`file:${relativePath}\n`);
      hasher.update(fs.readFileSync(absolute));
      hasher.update("\n");
    } else if (entry.isDirectory()) {
      hasher.update(`dir:${relativePath}\n`);
      hashDirectoryInto(absolute, hasher, relativePath);
    } else if (entry.isFile()) {
      hasher.update(`file:${relativePath}\n`);
      hasher.update(fs.readFileSync(absolute));
      hasher.update("\n");
    }
  }
}

function copyRuntimeInputs(
  paths: RequiredPaths,
  stage: string,
  sourceContentCache: SourceContentCache,
): void {
  const stageSrc = join(stage, "src");
  fs.mkdirSync(stage, { recursive: true });
  syncManagedTree(paths.srcDir, stageSrc, [], sourceContentCache);
  fs.copyFileSync(paths.packageJson, join(stage, "package.json"));
  fs.copyFileSync(paths.tsconfigJson, join(stage, "tsconfig.json"));
  fs.copyFileSync(paths.bunLock, join(stage, "bun.lock"));
}

function isCompleteRelease(releaseDir: string): boolean {
  try {
    return (
      fs.existsSync(join(releaseDir, "src", "cli.ts")) &&
      fs.statSync(join(releaseDir, "node_modules")).isDirectory()
    );
  } catch {
    return false;
  }
}

function createStage(releasesRoot: string): string {
  const nonce = crypto.randomBytes(8).toString("hex");
  const stage = join(releasesRoot, `.stage-${process.pid}-${nonce}`);
  if (fs.existsSync(stage)) {
    throw new Error(`runtime stage collision: ${stage}`);
  }
  return stage;
}

function publishAndPrune(job: SyncRuntimeInstallJob, releaseDir: string): boolean {
  if (!publishCurrentLink(job.currentLink, releaseDir)) {
    return false;
  }
  pruneUnreferencedReleases(job.releasesRoot, releaseDir);
  return true;
}

function publishCurrentLink(currentLink: string, releaseDir: string): boolean {
  const parent = dirname(currentLink);
  fs.mkdirSync(parent, { recursive: true });
  const temp = `${currentLink}.${process.pid}.tmp`;
  try {
    rmEntry(temp);
    const target = relative(parent, releaseDir);
    fs.symlinkSync(target, temp, "dir");
    fs.renameSync(temp, currentLink);
  } catch (error) {
    err(`failed to publish current link ${currentLink}: ${panicMessage(error)}`);
    try {
      rmEntry(temp);
    } catch {
      // ignore
    }
    return false;
  }
  return true;
}

function pruneUnreferencedReleases(releasesRoot: string, currentReleaseDir: string): void {
  const currentBase = basename(currentReleaseDir);
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(releasesRoot, { withFileTypes: true });
  } catch (error) {
    warn(`failed to list releases for pruning: ${panicMessage(error)}`);
    return;
  }
  for (const entry of entries) {
    if (entry.name.startsWith(".") || !entry.isDirectory() || entry.name === currentBase) {
      continue;
    }
    try {
      fs.rmSync(join(releasesRoot, entry.name), { recursive: true, force: true });
    } catch (error) {
      warn(`failed to prune unreferenced release ${entry.name}: ${panicMessage(error)}`);
    }
  }
}

export function removeLegacyRuntimeInstall(runtimeHome: string): boolean {
  const legacy = join(runtimeHome, "sync");
  try {
    if (!fs.existsSync(legacy)) {
      return true;
    }
    const metadata = fs.lstatSync(legacy);
    if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
      return true;
    }
    fs.rmSync(legacy, { recursive: true, force: true });
    return true;
  } catch (error) {
    err(`legacy runtime cleanup failed: ${legacy} (${panicMessage(error)})`);
    return false;
  }
}

function syncDirInto(
  srcDir: string,
  dstDir: string,
  preservePaths: readonly string[],
  sourceContentCache: SourceContentCache,
): boolean {
  try {
    if (!isDirectoryLike(srcDir)) {
      err(`missing directory: ${srcDir}`);
      return true;
    }

    fs.mkdirSync(dstDir, { recursive: true });
    syncManagedChildren(srcDir, dstDir, preservePaths, sourceContentCache);
    return true;
  } catch (error) {
    err(`copy failed: ${srcDir} -> ${dstDir} (${panicMessage(error)})`);
    return false;
  }
}

function syncManagedDir(
  srcDir: string,
  dstDir: string,
  preservePaths: readonly string[],
  sourceContentCache: SourceContentCache,
): boolean {
  try {
    if (!isDirectoryLike(srcDir)) {
      err(`missing directory: ${srcDir}`);
      return true;
    }

    fs.mkdirSync(dirname(dstDir), { recursive: true });
    syncManagedTree(srcDir, dstDir, preservePaths, sourceContentCache);
    return true;
  } catch (error) {
    err(`copy failed: ${srcDir} -> ${dstDir} (${panicMessage(error)})`);
    return false;
  }
}

function syncItem(src: string, dst: string): boolean {
  try {
    if (!fs.existsSync(src) && !isSymlink(src)) {
      err(`missing source: ${src}`);
      return true;
    }

    if (filesMatch(src, dst)) {
      return true;
    }

    fs.mkdirSync(dirname(dst), { recursive: true });
    rmEntry(dst);
    fs.copyFileSync(src, dst);
    return true;
  } catch (error) {
    err(`copy failed: ${src} -> ${dst} (${panicMessage(error)})`);
    return false;
  }
}

function isDirectoryLike(path: string): boolean {
  try {
    return fs.statSync(path).isDirectory();
  } catch {
    return false;
  }
}

function filesMatch(src: string, dst: string): boolean {
  try {
    if (isSymlink(dst)) {
      return false;
    }
    const srcStat = fs.statSync(src);
    const dstStat = fs.statSync(dst);
    if (!srcStat.isFile() || !dstStat.isFile()) {
      return false;
    }
    if (srcStat.size !== dstStat.size) {
      return false;
    }
    if ((srcStat.mode & 0o777) !== (dstStat.mode & 0o777)) {
      return false;
    }
    if (srcStat.size === 0) {
      return true;
    }
    return fs.readFileSync(src).equals(fs.readFileSync(dst));
  } catch {
    return false;
  }
}
