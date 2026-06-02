import fs from "node:fs";
import path from "node:path";
import { isErrno } from "./errors.ts";

export function isSymlink(targetPath: string): boolean {
  try {
    return fs.lstatSync(targetPath).isSymbolicLink();
  } catch {
    return false;
  }
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
  const metadata = fs.statSync(src);
  if (!metadata.isDirectory()) {
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.copyFileSync(src, dst);
    return;
  }
  copyTreeRecursive(src, dst);
}

export function syncManagedTree(
  src: string,
  dst: string,
  preservePaths: readonly string[] = [],
): void {
  const metadata = fs.statSync(src);
  if (!metadata.isDirectory()) {
    syncManagedFile(src, dst);
    return;
  }
  syncManagedTreeRecursive(src, dst, normalizePreservePaths(preservePaths));
}

export function syncManagedChildren(
  src: string,
  dst: string,
  preservePaths: readonly string[] = [],
): void {
  const metadata = fs.statSync(src);
  if (!metadata.isDirectory()) {
    syncManagedFile(src, dst);
    return;
  }
  syncManagedChildrenRecursive(src, dst, normalizePreservePaths(preservePaths));
}

function copyTreeRecursive(src: string, dst: string): void {
  const metadata = fs.statSync(src);
  if (!metadata.isDirectory()) {
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.copyFileSync(src, dst);
    return;
  }

  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const childSrc = path.join(src, entry.name);
    const childDst = path.join(dst, entry.name);
    const childMetadata = fs.statSync(childSrc);
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
): void {
  const metadata = fs.statSync(src);
  if (!metadata.isDirectory()) {
    syncManagedFile(src, dst);
    return;
  }

  ensureDirectory(dst);

  const srcEntries = fs.readdirSync(src, { withFileTypes: true });
  const srcNames = new Set(srcEntries.map((entry) => entry.name));

  for (const dstEntry of safeReadDir(dst)) {
    if (srcNames.has(dstEntry.name)) {
      continue;
    }
    if (preservePaths.includes(dstEntry.name)) {
      continue;
    }
    rmEntry(path.join(dst, dstEntry.name));
  }

  for (const srcEntry of srcEntries) {
    const childSrc = path.join(src, srcEntry.name);
    const childDst = path.join(dst, srcEntry.name);
    const childPreservePaths = childPreserve(preservePaths, srcEntry.name);
    const childMetadata = fs.statSync(childSrc);
    if (childMetadata.isDirectory()) {
      syncManagedTreeRecursive(childSrc, childDst, childPreservePaths);
      continue;
    }
    syncManagedFile(childSrc, childDst);
  }
}

function syncManagedChildrenRecursive(
  src: string,
  dst: string,
  preservePaths: readonly string[],
): void {
  const metadata = fs.statSync(src);
  if (!metadata.isDirectory()) {
    syncManagedFile(src, dst);
    return;
  }

  ensureDirectory(dst);

  for (const srcEntry of fs.readdirSync(src, { withFileTypes: true })) {
    const childSrc = path.join(src, srcEntry.name);
    const childDst = path.join(dst, srcEntry.name);
    const childPreservePaths = childPreserve(preservePaths, srcEntry.name);
    const childMetadata = fs.statSync(childSrc);
    if (childMetadata.isDirectory()) {
      syncManagedTreeRecursive(childSrc, childDst, childPreservePaths);
      continue;
    }
    syncManagedFile(childSrc, childDst);
  }
}

function syncManagedFile(src: string, dst: string): void {
  const srcMetadata = fs.statSync(src);
  if (isIdenticalFile(src, srcMetadata, dst)) {
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

  const srcContent = fs.readFileSync(src);
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

function childPreserve(
  preservePaths: readonly string[],
  childName: string,
): string[] {
  const prefix = `${childName}/`;
  return preservePaths
    .filter((candidate) => candidate.startsWith(prefix))
    .map((candidate) => candidate.slice(prefix.length));
}

const normalizePreservePaths = (preservePaths: readonly string[]): string[] =>
  [
    ...new Set(preservePaths.filter((candidate) => candidate.length > 0)),
  ].sort();

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
