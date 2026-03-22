import fs from "node:fs";
import { dirname } from "node:path";

import { SyncEnv } from "./harness.ts";
import { err, panicMessage } from "./lib.ts";
import { buildSyncPlan, type Job } from "./plan.ts";
import { copyTree, isSymlink, rmEntry } from "./runtime/fs.ts";

export type { JobKind } from "./plan.ts";
export type { Job } from "./plan.ts";

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

export function iterJobs(syncEnv: SyncEnv): Job[] {
  return [...buildSyncPlan(syncEnv).jobs];
}

export function runJobs(jobs: readonly Job[]): boolean {
  return jobs.every((job) => runJob(job));
}

function runJob(job: Job): boolean {
  try {
    return job.kind === "Dir"
      ? copyDirInto(job.src, job.dst)
      : copyItem(job.src, job.dst);
  } catch (error) {
    err(`unexpected error in ${job.kind === "Dir" ? "copy_dir_into" : "copy_item"}: ${panicMessage(error)}`);
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
