import fs from "node:fs";
import path from "node:path";
import { isErrno } from "./errors.ts";

type SourceContentCache = Map<string, { readonly metadata: fs.Stats; readonly content: Buffer }>;

const IGNORED_SYNC_NAMES: Record<string, true> = {
  ".venv": true,
  node_modules: true,
  __pycache__: true,
  ".pytest_cache": true,
  ".ruff_cache": true,
  ".hypothesis": true,
  ".DS_Store": true,
  ".git": true,
};

export function isIgnoredSyncEntry(name: string): boolean {
  return (
    IGNORED_SYNC_NAMES[name] === true ||
    name.endsWith(".pyc") ||
    name.endsWith(".pyo")
  );
}

export function isSymlink(targetPath: string): boolean {
  try {
    return fs.lstatSync(targetPath).isSymbolicLink();
  } catch (error) {
    if (isErrno(error, "ENOENT")) {
      return false;
    }
    throw error;
  }
}

function resolveSourceEntry(src: string): fs.Stats {
  const metadata = fs.lstatSync(src);
  if (metadata.isSymbolicLink()) {
    const targetMetadata = fs.statSync(src);
    if (targetMetadata.isDirectory()) {
      throw new Error(`refusing source directory symlink: ${src}`);
    }
    return targetMetadata;
  }
  return metadata;
}

export function rmEntry(targetPath: string): void {
  try {
    const metadata = fs.lstatSync(targetPath);
    if (metadata.isSymbolicLink() || metadata.isFile()) {
      fs.unlinkSync(targetPath);
      return;
    }
    if (metadata.isDirectory()) {
      fs.rmSync(targetPath, { recursive: true, force: false });
      return;
    }
    fs.unlinkSync(targetPath);
  } catch (error) {
    if (!isErrno(error, "ENOENT")) {
      throw error;
    }
  }
}

export function copyTree(src: string, dst: string): void {
  const metadata = resolveSourceEntry(src);
  if (metadata.isDirectory()) {
    copyTreeRecursive(src, dst);
    return;
  }
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.copyFileSync(src, dst);
}

export function syncManagedTree(
  src: string,
  dst: string,
  preservePaths: readonly string[] = [],
  sourceContentCache?: SourceContentCache,
): void {
  const metadata = resolveSourceEntry(src);
  if (!metadata.isDirectory()) {
    syncManagedFile(src, dst, metadata, sourceContentCache);
    return;
  }
  syncManagedTreeRecursive(src, dst, normalizePreservePaths(preservePaths), sourceContentCache);
}

export function syncManagedChildren(
  src: string,
  dst: string,
  preservePaths: readonly string[] = [],
  sourceContentCache?: SourceContentCache,
): void {
  const metadata = resolveSourceEntry(src);
  if (!metadata.isDirectory()) {
    syncManagedFile(src, dst, metadata, sourceContentCache);
    return;
  }
  syncManagedChildrenRecursive(src, dst, normalizePreservePaths(preservePaths), sourceContentCache);
}

function copyTreeRecursive(src: string, dst: string): void {
  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (isIgnoredSyncEntry(entry.name)) {
      continue;
    }
    const childSrc = path.join(src, entry.name);
    const childDst = path.join(dst, entry.name);
    const childMetadata = resolveSourceEntry(childSrc);
    if (childMetadata.isDirectory()) {
      copyTreeRecursive(childSrc, childDst);
    } else {
      fs.mkdirSync(path.dirname(childDst), { recursive: true });
      fs.copyFileSync(childSrc, childDst);
    }
  }
}

function syncManagedTreeRecursive(
  src: string,
  dst: string,
  preservePaths: readonly string[],
  sourceContentCache?: SourceContentCache,
): void {
  const metadata = resolveSourceEntry(src);
  if (!metadata.isDirectory()) {
    syncManagedFile(src, dst, metadata, sourceContentCache);
    return;
  }

  ensureDirectory(dst);

  const srcEntries = fs
    .readdirSync(src, { withFileTypes: true })
    .filter((entry) => !isIgnoredSyncEntry(entry.name));
  const srcNames = new Set(srcEntries.map((entry) => entry.name));

  for (const dstEntry of safeReadDir(dst)) {
    if (srcNames.has(dstEntry.name)) {
      continue;
    }
    if (preservePaths.includes(dstEntry.name)) {
      continue;
    }
    const childDst = path.join(dst, dstEntry.name);
    if (
      preservesEntry(preservePaths, dstEntry.name) &&
      dstEntry.isDirectory() &&
      !dstEntry.isSymbolicLink()
    ) {
      pruneManagedTree(childDst, childPreserve(preservePaths, dstEntry.name));
      continue;
    }
    rmEntry(childDst);
  }

  for (const srcEntry of srcEntries) {
    if (preservePaths.includes(srcEntry.name)) {
      continue;
    }
    const childSrc = path.join(src, srcEntry.name);
    const childDst = path.join(dst, srcEntry.name);
    const childPreservePaths = childPreserve(preservePaths, srcEntry.name);
    const childMetadata = resolveSourceEntry(childSrc);
    if (childMetadata.isDirectory()) {
      syncManagedTreeRecursive(childSrc, childDst, childPreservePaths, sourceContentCache);
      continue;
    }
    syncManagedFile(childSrc, childDst, childMetadata, sourceContentCache);
  }
}

function syncManagedChildrenRecursive(
  src: string,
  dst: string,
  preservePaths: readonly string[],
  sourceContentCache?: SourceContentCache,
): void {
  const metadata = resolveSourceEntry(src);
  if (!metadata.isDirectory()) {
    syncManagedFile(src, dst, metadata, sourceContentCache);
    return;
  }

  for (const srcEntry of fs.readdirSync(src, { withFileTypes: true })) {
    if (isIgnoredSyncEntry(srcEntry.name) || preservePaths.includes(srcEntry.name)) {
      continue;
    }
    const childSrc = path.join(src, srcEntry.name);
    const childDst = path.join(dst, srcEntry.name);
    const childPreservePaths = childPreserve(preservePaths, srcEntry.name);
    const childMetadata = resolveSourceEntry(childSrc);
    if (childMetadata.isDirectory()) {
      syncManagedTreeRecursive(childSrc, childDst, childPreservePaths, sourceContentCache);
      continue;
    }
    syncManagedFile(childSrc, childDst, childMetadata, sourceContentCache);
  }
}

function syncManagedFile(
  src: string,
  dst: string,
  srcMetadata: fs.Stats,
  sourceContentCache?: SourceContentCache,
): void {
  if (isIdenticalFile(src, srcMetadata, dst, sourceContentCache)) {
    return;
  }

  fs.mkdirSync(path.dirname(dst), { recursive: true });
  rmEntry(dst);
  fs.copyFileSync(src, dst);
}

function isIdenticalFile(
  src: string,
  srcMetadata: fs.Stats,
  dst: string,
  sourceContentCache?: SourceContentCache,
): boolean {
  if (srcMetadata.isDirectory()) {
    return false;
  }

  let dstMetadata: fs.Stats;
  try {
    if (fs.lstatSync(dst).isSymbolicLink()) {
      return false;
    }
    dstMetadata = fs.statSync(dst);
  } catch {
    return false;
  }

  if (!dstMetadata.isFile()) {
    return false;
  }
  if (srcMetadata.size !== dstMetadata.size) {
    return false;
  }
  if ((srcMetadata.mode & 0o777) !== (dstMetadata.mode & 0o777)) {
    return false;
  }
  if (srcMetadata.size === 0) {
    return true;
  }

  const cached = sourceContentCache?.get(src);
  const srcContent =
    cached &&
    cached.metadata.size === srcMetadata.size &&
    cached.metadata.mode === srcMetadata.mode &&
    cached.metadata.mtimeMs === srcMetadata.mtimeMs &&
    cached.metadata.ctimeMs === srcMetadata.ctimeMs
      ? cached.content
      : fs.readFileSync(src);
  if (sourceContentCache && srcContent !== cached?.content) {
    sourceContentCache.set(src, { metadata: srcMetadata, content: srcContent });
  }
  const dstContent = fs.readFileSync(dst);
  return srcContent.equals(dstContent);
}

function ensureDirectory(dst: string): void {
  try {
    const metadata = fs.lstatSync(dst);
    if (metadata.isDirectory() && !metadata.isSymbolicLink()) {
      return;
    }
    rmEntry(dst);
  } catch (error) {
    if (!isErrno(error, "ENOENT")) {
      throw error;
    }
  }
  fs.mkdirSync(dst, { recursive: true });
}

function childPreserve(preservePaths: readonly string[], childName: string): string[] {
  const prefix = `${childName}/`;
  return preservePaths
    .filter((candidate) => candidate.startsWith(prefix))
    .map((candidate) => candidate.slice(prefix.length));
}

const preservesEntry = (paths: readonly string[], name: string): boolean =>
  paths.some((entry) => entry === name || entry.startsWith(`${name}/`));

function pruneManagedTree(dst: string, preservePaths: readonly string[]): void {
  for (const dstEntry of safeReadDir(dst)) {
    if (preservePaths.includes(dstEntry.name)) {
      continue;
    }
    const childDst = path.join(dst, dstEntry.name);
    if (
      preservesEntry(preservePaths, dstEntry.name) &&
      dstEntry.isDirectory() &&
      !dstEntry.isSymbolicLink()
    ) {
      pruneManagedTree(childDst, childPreserve(preservePaths, dstEntry.name));
      continue;
    }
    rmEntry(childDst);
  }
}

const normalizePreservePaths = (preservePaths: readonly string[]): string[] =>
  [...new Set(preservePaths.filter((candidate) => candidate.length > 0))].toSorted();

function safeReadDir(targetPath: string): fs.Dirent[] {
  try {
    return fs.readdirSync(targetPath, { withFileTypes: true });
  } catch (error) {
    if (isErrno(error, "ENOENT")) {
      return [];
    }
    throw error;
  }
}
