import fs from "node:fs";
import { dirname } from "node:path";
import { assertNever, err, panicMessage, warn } from "@runtime/errors.ts";
import { copyTree, isSymlink, rmEntry, syncManagedChildren, syncManagedTree } from "@runtime/fs.ts";
import { syncCliProxyConfig } from "./cliproxy-config.ts";
import type { Job } from "./plan.ts";
import { syncSecretTemplate } from "./secret-template.ts";

type SourceContentCache = Map<string, { readonly metadata: fs.Stats; readonly content: Buffer }>;

export type { Job, JobKind } from "./plan.ts";

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

export function runJobsWithPreserve(
  jobs: readonly Job[],
  preservePathsByDst: ReadonlyMap<string, readonly string[]> = new Map(),
): boolean {
  const sourceContentCache: SourceContentCache = new Map();
  return jobs.every((job) => runJob(job, preservePathsByDst, sourceContentCache));
}

function runJob(
  job: Job,
  preservePathsByDst: ReadonlyMap<string, readonly string[]>,
  sourceContentCache: SourceContentCache,
): boolean {
  try {
    switch (job.kind) {
      case "Dir":
        return job.scope === "Children"
          ? syncDirInto(job.src, job.dst, preservePathsByDst.get(job.dst) ?? [], sourceContentCache)
          : syncManagedDir(
              job.src,
              job.dst,
              preservePathsByDst.get(job.dst) ?? [],
              sourceContentCache,
            );
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
      case "CliProxyConfig":
        if (!fs.existsSync(job.src)) {
          err(`missing source: ${job.src}`);
          return true;
        }
        if (!fs.existsSync(job.secretsPath)) {
          warn(`missing local secrets ${job.secretsPath}; skipping ${job.dst}`);
          return true;
        }
        syncCliProxyConfig(job.src, job.dst, job.secretsPath);
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
