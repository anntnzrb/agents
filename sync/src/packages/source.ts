import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";

import { rmEntry } from "@runtime/fs.ts";
import { commandExists } from "@runtime/process.ts";
import { runCommand } from "./process.ts";

export { rmEntry } from "@runtime/fs.ts";

const ALPHANUMERIC_PATTERN = /[A-Za-z0-9]/;
const SOURCE_SEPARATOR_PATTERN = /[/:]/;
const TRAILING_PATH_SEPARATOR_PATTERN = /\/+$/;

export function packageCacheDir(cacheRoot: string, source: string): string {
  const slug = sourceSlug(source);
  return path.join(cacheRoot, `${slug}-${fnv1a64(source)}`);
}

export function stagingDirFor(finalDir: string): string {
  const now = BigInt(Date.now()) * 1000000n;
  return withExtension(finalDir, `staging-${process.pid}-${now}`);
}

export async function replaceDirAtomically(src: string, dst: string): Promise<void> {
  const now = BigInt(Date.now()) * 1000000n;
  const backup = withExtension(dst, `backup-${process.pid}-${now}`);
  const legacyBackup = withExtension(dst, "backup");
  if (exists(legacyBackup)) {
    rmEntry(legacyBackup);
  }
  rmEntry(backup);
  let movedToBackup = false;
  if (exists(dst)) {
    await fsp.rename(dst, backup);
    movedToBackup = true;
  }

  try {
    await fsp.rename(src, dst);
    if (movedToBackup) {
      rmEntry(backup);
    }
  } catch (error) {
    if (movedToBackup && exists(backup)) {
      try {
        await fsp.rename(backup, dst);
      } catch {
        // best-effort rollback only
      }
    }
    throw error;
  }
}

export async function clonePackage(
  source: string,
  targetDir: string,
  timeoutMs: number,
): Promise<boolean> {
  // clonePackageWithRunner removes the target directory between attempts and after
  // every failure. We only call it with a private staging directory from stagingDirFor.
  return clonePackageWithRunner(source, targetDir, await commandExists("gh"), (command) =>
    runCommand(command, undefined, timeoutMs, "clone"),
  );
}

function sourceSlug(source: string): string {
  const trimmed = source.trim().replace(TRAILING_PATH_SEPARATOR_PATTERN, "");
  const normalized = trimmed.endsWith(".git") ? trimmed.slice(0, -4) : trimmed;
  const sourceParts = isLocalPathSource(normalized)
    ? [localPathBasename(normalized)]
    : normalized
        .split(SOURCE_SEPARATOR_PATTERN)
        .filter((part) => part.length > 0)
        .slice(-2);
  const joined = sourceParts.length === 0 ? "package" : sourceParts.join("-");
  const sanitized = joined
    .split("")
    .map((ch) => (ALPHANUMERIC_PATTERN.test(ch) ? ch.toLowerCase() : "-"))
    .join("");
  const compact = sanitized
    .split("-")
    .filter((part) => part.length > 0)
    .join("-");
  return compact.length > 0 ? compact : "package";
}

const localPathBasename = (source: string): string => path.basename(source);

const isLocalPathSource = (source: string): boolean => path.isAbsolute(source);

function fnv1a64(input: string): string {
  let hash = 0xcbf29ce484222325n;
  for (const byte of new TextEncoder().encode(input)) {
    hash ^= BigInt(byte);
    hash = (hash * 0x100000001b3n) & 0xffffffffffffffffn;
  }
  return hash.toString(16).padStart(16, "0");
}

function withExtension(target: string, extension: string): string {
  const dir = path.dirname(target);
  const base = path.basename(target);
  const ext = path.extname(base);
  const stem = ext ? base.slice(0, -ext.length) : base;
  return path.join(dir, `${stem}.${extension}`);
}

export async function clonePackageWithRunner(
  source: string,
  targetDir: string,
  ghAvailable: boolean,
  runner: (command: readonly string[]) => Promise<boolean>,
): Promise<boolean> {
  const commands = cloneCommands(source, targetDir, ghAvailable);
  let index = 0;
  for (const command of commands) {
    if (index > 0) {
      rmEntry(targetDir);
    }
    index += 1;
    if (await runner(command)) {
      return true;
    }
    rmEntry(targetDir);
  }
  return false;
}

function cloneCommands(source: string, targetDir: string, ghAvailable: boolean): string[][] {
  const commands: string[][] = [];
  const slug = githubRepoSlug(source);
  if (slug && ghAvailable) {
    commands.push(["gh", "repo", "clone", slug, targetDir, "--", "--depth=1"]);
  }
  commands.push(["git", "clone", "--depth=1", source, targetDir]);
  return commands;
}

function githubRepoSlug(source: string): string | null {
  const trimmed = source.trim();
  const normalized = trimmed.endsWith(".git") ? trimmed.slice(0, -4) : trimmed;
  if (normalized.startsWith("https://github.com/")) {
    return splitOwnerRepo(normalized.slice("https://github.com/".length));
  }
  if (normalized.startsWith("http://github.com/")) {
    return splitOwnerRepo(normalized.slice("http://github.com/".length));
  }
  if (normalized.startsWith("git@github.com:")) {
    return splitOwnerRepo(normalized.slice("git@github.com:".length));
  }
  return null;
}

function splitOwnerRepo(rest: string): string | null {
  const parts = rest
    .split("/")
    .filter((part) => part.length > 0)
    .slice(0, 2);
  if (parts.length !== 2) {
    return null;
  }
  return `${parts[0]}/${parts[1]}`;
}

function exists(target: string): boolean {
  try {
    fs.accessSync(target);
    return true;
  } catch {
    return false;
  }
}
