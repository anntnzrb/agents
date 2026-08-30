import { describe, expect, test } from "bun:test";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { copyTree, isSymlink, rmEntry, syncManagedChildren, syncManagedTree } from "@runtime/fs.ts";

async function withTempDir<T>(fn: (dir: string) => T | Promise<T>): Promise<T> {
  const dir = mkdtempSync(join(tmpdir(), "runtime-fs-test-"));
  try {
    return await fn(dir);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

const isRoot = typeof process.getuid === "function" && process.getuid() === 0;

describe("runtime/fs.ts", () => {
  test("isSymlink is true for symlinks, false for regular files, and only swallows ENOENT", async () => {
    await withTempDir(async (dir) => {
      const file = join(dir, "file.txt");
      const link = join(dir, "link");
      const missing = join(dir, "missing");
      writeFileSync(file, "hello");
      symlinkSync(file, link);

      expect(isSymlink(link)).toBe(true);
      expect(isSymlink(file)).toBe(false);
      expect(isSymlink(missing)).toBe(false);

      if (!isRoot) {
        const locked = join(dir, "locked");
        mkdirSync(locked);
        chmodSync(locked, 0o000);
        try {
          expect(() => isSymlink(join(locked, "x"))).toThrow();
        } finally {
          chmodSync(locked, 0o755);
        }
      }
    });
  });

  test("rmEntry removes files, directories, symlinks, and ignores missing", async () => {
    await withTempDir(async (dir) => {
      const file = join(dir, "file.txt");
      const sub = join(dir, "sub");
      const link = join(dir, "link");
      const missing = join(dir, "missing");

      writeFileSync(file, "hello");
      mkdirSync(join(sub, "nested"), { recursive: true });
      writeFileSync(join(sub, "nested", "child.txt"), "child");
      symlinkSync(file, link);

      rmEntry(link);
      expect(existsSync(link)).toBe(false);

      rmEntry(file);
      expect(existsSync(file)).toBe(false);

      rmEntry(sub);
      expect(existsSync(sub)).toBe(false);

      rmEntry(missing);
      expect(existsSync(missing)).toBe(false);
    });
  });

  test("copyTree mirrors files and rejects source directory symlinks", async () => {
    await withTempDir(async (dir) => {
      const src = join(dir, "src");
      const cyclic = join(dir, "cyclic");
      mkdirSync(join(src, "sub"), { recursive: true });
      writeFileSync(join(src, "file1.txt"), "hello");
      writeFileSync(join(src, "sub", "file2.txt"), "world");

      copyTree(src, join(dir, "dst"));
      expect(readFileSync(join(dir, "dst", "file1.txt"), "utf8")).toBe("hello");
      expect(readFileSync(join(dir, "dst", "sub", "file2.txt"), "utf8")).toBe("world");

      // Copying a single file through a symlink to a file is allowed.
      const singleDst = join(dir, "single.txt");
      copyTree(join(src, "file1.txt"), singleDst);
      expect(readFileSync(singleDst, "utf8")).toBe("hello");

      // A self-referential source directory symlink is rejected.
      mkdirSync(cyclic);
      symlinkSync(cyclic, join(cyclic, "self"), "dir");
      expect(() => copyTree(cyclic, join(dir, "dst2"))).toThrow(
        "refusing source directory symlink:",
      );
    });
  });

  test("syncManagedChildren copies only children", async () => {
    await withTempDir(async (dir) => {
      const src = join(dir, "src");
      mkdirSync(src);
      writeFileSync(join(src, "child.txt"), "child");

      syncManagedChildren(src, join(dir, "dst"));
      expect(readFileSync(join(dir, "dst", "child.txt"), "utf8")).toBe("child");
    });
  });

  test("syncManagedTree keeps nested preserved files and removes stale entries", async () => {
    await withTempDir(async (dir) => {
      const src = join(dir, "src");
      const dst = join(dir, "dst");
      mkdirSync(join(src, "sub"), { recursive: true });
      writeFileSync(join(src, "file1.txt"), "hello");
      writeFileSync(join(src, "sub", "file3.txt"), "world");

      mkdirSync(join(dst, "preserved"), { recursive: true });
      writeFileSync(join(dst, "preserved", "nested.txt"), "keep");
      writeFileSync(join(dst, "preserved", "stale.txt"), "delete");
      writeFileSync(join(dst, "other.txt"), "delete");

      syncManagedTree(src, dst, ["preserved/nested.txt"]);

      expect(readFileSync(join(dst, "file1.txt"), "utf8")).toBe("hello");
      expect(readFileSync(join(dst, "sub", "file3.txt"), "utf8")).toBe("world");
      expect(readFileSync(join(dst, "preserved", "nested.txt"), "utf8")).toBe("keep");
      expect(existsSync(join(dst, "preserved", "stale.txt"))).toBe(false);
      expect(existsSync(join(dst, "other.txt"))).toBe(false);
    });
  });

  test("syncManagedTree removes destination symlinks without following them", async () => {
    await withTempDir(async (dir) => {
      const src = join(dir, "src");
      const dst = join(dir, "dst");
      const external = join(dir, "external");

      mkdirSync(src);
      writeFileSync(join(src, "file1.txt"), "hello");

      mkdirSync(external);
      writeFileSync(join(external, "untouched.txt"), "untouched");

      mkdirSync(dst);
      symlinkSync(external, join(dst, "link"), "dir");

      syncManagedTree(src, dst);

      expect(readFileSync(join(dst, "file1.txt"), "utf8")).toBe("hello");
      expect(existsSync(join(dst, "link"))).toBe(false);
      expect(readFileSync(join(external, "untouched.txt"), "utf8")).toBe("untouched");
      expect(existsSync(join(external, "file1.txt"))).toBe(false);
    });
  });

  test("syncManagedTree throws on inaccessible source", async () => {
    if (isRoot) {
      return;
    }
    await withTempDir(async (dir) => {
      const src = join(dir, "src");
      const dst = join(dir, "dst");
      mkdirSync(src);
      writeFileSync(join(src, "file1.txt"), "hello");
      chmodSync(src, 0o000);
      try {
        expect(() => syncManagedTree(src, dst)).toThrow();
      } finally {
        chmodSync(src, 0o755);
      }
    });
  });

  test("syncManagedTree throws on self-referential source directory symlink", async () => {
    await withTempDir(async (dir) => {
      const src = join(dir, "src");
      const dst = join(dir, "dst");
      mkdirSync(src);
      symlinkSync(src, join(src, "self"), "dir");

      expect(() => syncManagedTree(src, dst)).toThrow("refusing source directory symlink:");
      expect(existsSync(dst)).toBe(true);
      expect(readdirSync(dst).length).toBe(0);
    });
  });
});
