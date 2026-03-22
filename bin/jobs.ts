import fs from "node:fs";
import { dirname, join } from "node:path";

import { SOURCE_AGENT_FILE, SyncEnv } from "./harness.ts";
import { assetDirNames } from "./managed.ts";
import { copyTree, err, isSymlink, panicMessage, rmEntry } from "./lib.ts";

export type JobKind = "File" | "Dir";

export interface Job {
  src: string;
  dst: string;
  kind: JobKind;
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

export function iterJobs(syncEnv: SyncEnv): Job[] {
  const jobs: Job[] = [];
  jobs.push(...harnessDirs(syncEnv));
  jobs.push(...assetCopies(syncEnv));
  jobs.push(...agentFiles(syncEnv));
  jobs.push(...configFiles(syncEnv));
  return jobs;
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

function harnessDirs(syncEnv: SyncEnv): Job[] {
  return syncEnv.harnesses.map((harness) => ({
    src: harness.sourceRoot(syncEnv.toolsHome),
    dst: harness.root(),
    kind: "Dir",
  }));
}

function assetCopies(syncEnv: SyncEnv): Job[] {
  const jobs: Job[] = [];
  for (const assetName of assetDirNames(syncEnv.assetsHome)) {
    const assetPath = join(syncEnv.assetsHome, assetName);
    for (const harness of syncEnv.harnesses) {
      jobs.push({
        src: assetPath,
        dst: join(harness.root(), harness.renameAsset(assetName)),
        kind: "Dir",
      });
    }
  }
  return jobs;
}

function agentFiles(syncEnv: SyncEnv): Job[] {
  return syncEnv.harnesses.map((harness) => ({
    src: join(syncEnv.assetsHome, SOURCE_AGENT_FILE),
    dst: harness.instructionTarget(),
    kind: "File",
  }));
}

function configFiles(syncEnv: SyncEnv): Job[] {
  return [
    {
      src: join(syncEnv.assetsHome, "mcporter.jsonc"),
      dst: join(syncEnv.mcporterHome, "mcporter.json"),
      kind: "File",
    },
  ];
}

function isDirectoryLike(path: string): boolean {
  try {
    return fs.statSync(path).isDirectory();
  } catch {
    return false;
  }
}
