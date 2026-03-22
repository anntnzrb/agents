import fs from "node:fs";
import path from "node:path";

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
    if (!isNotFound(error)) {
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

function isNotFound(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code?: unknown }).code === "ENOENT"
  );
}
