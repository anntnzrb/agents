import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";

import { rmEntry } from "@runtime/fs.ts";

export { rmEntry } from "@runtime/fs.ts";

const ALPHANUMERIC_PATTERN = /[A-Za-z0-9]/;
const SOURCE_SEPARATOR_PATTERN = /[/:]/;
const TRAILING_PATH_SEPARATOR_PATTERN = /\/+$/;

export interface PackageSourceRuntime {
  readonly fetch?: PackageFetch;
  readonly extract?: (archive: Uint8Array, destination: string, timeoutMs: number) => Promise<void>;
}

type PackageFetch = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export function packageCacheDir(cacheRoot: string, source: string): string {
  const slug = sourceSlug(source);
  return path.join(cacheRoot, `${slug}-${fnv1a64(source)}`);
}

export function stagingDirFor(finalDir: string): string {
  const now = BigInt(Date.now()) * 1000000n;
  return withExtension(finalDir, `staging-${process.pid}-${now}`);
}

export async function replaceDirAtomically(src: string, dst: string): Promise<void> {
  const backup = withExtension(dst, "backup");
  rmEntry(backup);
  if (exists(dst)) {
    await fsp.rename(dst, backup);
  }

  try {
    await fsp.rename(src, dst);
    rmEntry(backup);
  } catch (error) {
    if (exists(backup)) {
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
  runtime: PackageSourceRuntime = {},
): Promise<boolean> {
  const normalizedSource = source.trim();
  if (isLocalPathSource(normalizedSource)) {
    try {
      await fsp.cp(normalizedSource, targetDir, {
        recursive: true,
        errorOnExist: true,
        force: false,
      });
      return true;
    } catch {
      return false;
    }
  }

  const slug = githubRepoSlug(normalizedSource);
  if (!slug) {
    return false;
  }

  try {
    const response = await (runtime.fetch ?? fetch)(
      `https://codeload.github.com/${slug}/tar.gz/HEAD`,
      { signal: AbortSignal.timeout(timeoutMs) },
    );
    if (!response.ok) {
      return false;
    }

    const parentDir = path.dirname(targetDir);
    await fsp.mkdir(parentDir, { recursive: true });
    const extractionDir = await fsp.mkdtemp(path.join(parentDir, ".source."));
    try {
      const archive = new Uint8Array(await response.arrayBuffer());
      await (runtime.extract ?? extractArchive)(archive, extractionDir, timeoutMs);
      const entries = await fsp.readdir(extractionDir, { withFileTypes: true });
      if (entries.length !== 1 || !entries[0]?.isDirectory()) {
        return false;
      }
      await fsp.rename(path.join(extractionDir, entries[0].name), targetDir);
      return true;
    } finally {
      rmEntry(extractionDir);
    }
  } catch {
    return false;
  }
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

const isLocalPathSource = (source: string): boolean => path.isAbsolute(source) || exists(source);

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

async function extractArchive(
  archive: Uint8Array,
  destination: string,
  timeoutMs: number,
): Promise<void> {
  const startedAt = Date.now();
  await new Bun.Archive(archive).extract(destination);
  if (Date.now() - startedAt > timeoutMs) {
    throw new Error("archive extraction timed out");
  }
}

function githubRepoSlug(source: string): string | null {
  const trimmed = source.trim();
  const normalized = trimmed.endsWith(".git") ? trimmed.slice(0, -4) : trimmed;
  let repositoryPath: string;
  if (normalized.startsWith("git@github.com:")) {
    repositoryPath = normalized.slice("git@github.com:".length);
  } else {
    try {
      const url = new URL(normalized);
      if (url.hostname !== "github.com" && url.hostname !== "www.github.com") {
        return null;
      }
      repositoryPath = url.pathname;
    } catch {
      return null;
    }
  }
  return splitOwnerRepo(repositoryPath);
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
