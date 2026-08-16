import fs from "node:fs";
import { dirname } from "node:path";
import { assertNever, err, panicMessage, warn } from "@runtime/errors.ts";
import { copyTree, isSymlink, rmEntry, syncManagedChildren, syncManagedTree } from "@runtime/fs.ts";
import { syncClientModelCatalog, syncCliProxyConfig } from "./cliproxy-config.ts";
import { isCliProxyTargetReady, publishCliProxyEndpointTemplates } from "./cliproxy-deployment.ts";
import type { Job } from "./plan.ts";
import { syncSecretTemplate } from "./secret-template.ts";

type SourceContentCache = Map<string, { readonly metadata: fs.Stats; readonly content: Buffer }>;

export type { Job, JobKind } from "./plan.ts";

export interface JobRunOptions {
  readonly forceModelRefresh?: boolean;
  readonly quietModelRefresh?: boolean;
}

interface JobRunState {
  cliProxyTargetReady: boolean | undefined;
}

export function copyItem(src: string, dst: string): boolean {
  try {
    if (!fs.existsSync(src) && !isSymlink(src)) {
      err(`missing source: ${src}`);
      return true;
    }

    fs.mkdirSync(dirname(dst), { recursive: true });
    rmEntry(dst);

    if (isDirectoryLike(src)) {
      copyTree(src, dst);
    } else {
      fs.copyFileSync(src, dst);
    }

    return true;
  } catch (error) {
    err(`copy failed: ${src} -> ${dst} (${panicMessage(error)})`);
    return false;
  }
}

export function copyDirInto(srcDir: string, dstDir: string): boolean {
  try {
    if (!isDirectoryLike(srcDir)) {
      err(`missing directory: ${srcDir}`);
      return true;
    }

    fs.mkdirSync(dstDir, { recursive: true });
    copyTree(srcDir, dstDir);
    return true;
  } catch (error) {
    err(`copy failed: ${srcDir} -> ${dstDir} (${panicMessage(error)})`);
    return false;
  }
}

export async function runJobsWithPreserve(
  jobs: readonly Job[],
  preservePathsByDst: ReadonlyMap<string, readonly string[]> = new Map(),
  options: JobRunOptions = {},
): Promise<boolean> {
  const sourceContentCache: SourceContentCache = new Map();
  const state: JobRunState = { cliProxyTargetReady: undefined };
  for (const job of jobs) {
    if (!(await runJob(job, preservePathsByDst, sourceContentCache, options, state))) {
      return false;
    }
  }
  return true;
}

async function runJob(
  job: Job,
  preservePathsByDst: ReadonlyMap<string, readonly string[]>,
  sourceContentCache: SourceContentCache,
  options: JobRunOptions,
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
        if (state.cliProxyTargetReady === false) {
          return true;
        }
        if (!fs.existsSync(job.src)) {
          err(`missing source: ${job.src}`);
          return true;
        }
        if (!fs.existsSync(job.secretsPath)) {
          if (job.gatewayHost === false) {
            await syncClientModelCatalog(job.src, job.deployment, {
              ...(job.cacheRoot === undefined ? {} : { cacheRoot: job.cacheRoot }),
              ...(job.runtimeRoot === undefined ? {} : { runtimeRoot: job.runtimeRoot }),
              ...(options.forceModelRefresh === undefined
                ? {}
                : { forceModelRefresh: options.forceModelRefresh }),
              ...(options.quietModelRefresh === undefined
                ? {}
                : { quietModelRefresh: options.quietModelRefresh }),
            });
            return true;
          }
          warn(`missing local secrets ${job.secretsPath}; skipping ${job.dst}`);
          return true;
        }
        await syncCliProxyConfig(job.src, job.dst, job.secretsPath, job.deployment, {
          writeServerConfig: job.gatewayHost !== false,
          ...(job.cacheRoot === undefined ? {} : { cacheRoot: job.cacheRoot }),
          ...(job.runtimeRoot === undefined ? {} : { runtimeRoot: job.runtimeRoot }),
          ...(options.forceModelRefresh === undefined
            ? {}
            : { forceModelRefresh: options.forceModelRefresh }),
          ...(options.quietModelRefresh === undefined
            ? {}
            : { quietModelRefresh: options.quietModelRefresh }),
        });
        return true;
      default:
        return assertNever(job);
    }
  } catch (error) {
    err(`unexpected error in ${job.kind}: ${panicMessage(error)}`);
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
