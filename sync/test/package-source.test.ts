import { describe, expect, test } from "bun:test";
import assert from "node:assert/strict";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { clonePackageWithRunner, replaceDirAtomically } from "@packages/source.ts";

function withTempDir<T>(fn: (root: string) => T | Promise<T>): Promise<T> {
  const root = mkdtempSync(join(tmpdir(), "package-source-test-"));
  return Promise.resolve(fn(root)).finally(() => {
    rmSync(root, { recursive: true, force: true });
  });
}

describe("packages/source.ts", () => {
  test("gh fallback removes partial files and leaves expected checkout", async () => {
    await withTempDir(async (root) => {
      const target = join(root, "out");
      mkdirSync(target, { recursive: true });
      const attempts: string[][] = [];
      let first = true;

      const result = await clonePackageWithRunner(
        "https://github.com/owner/repo",
        target,
        true,
        async (command) => {
          attempts.push([...command]);
          mkdirSync(target, { recursive: true });
          if (first) {
            first = false;
            writeFileSync(join(target, "partial.txt"), "partial");
            return false;
          }
          writeFileSync(join(target, "expected.txt"), "expected");
          return true;
        },
      );
      expect(result).toBe(true);
      expect(attempts[0]?.[0]).toBe("gh");
      expect(attempts[1]?.[0]).toBe("git");
      expect(() => readFileSync(join(target, "partial.txt"), "utf8")).toThrow();
    });
  });

  test("final failure removes all partial state", async () => {
    await withTempDir(async (root) => {
      const target = join(root, "out");
      mkdirSync(target, { recursive: true });
      const attempts: string[][] = [];

      const result = await clonePackageWithRunner(
        "https://github.com/owner/repo",
        target,
        true,
        async (command) => {
          attempts.push([...command]);
          mkdirSync(target, { recursive: true });
          writeFileSync(join(target, "partial.txt"), "partial");
          return false;
        },
      );
      expect(result).toBe(false);
      expect(attempts[0]?.[0]).toBe("gh");
      expect(attempts[1]?.[0]).toBe("git");
      expect(() => readFileSync(join(target, "partial.txt"), "utf8")).toThrow();
    });
  });

  test("replaceDirAtomically cleans up backup directories on success", async () => {
    await withTempDir(async (root) => {
      const dst = join(root, "my-package");
      const src = join(root, "my-package.staging-123-456");
      mkdirSync(dst, { recursive: true });
      writeFileSync(join(dst, "file.txt"), "old-version");
      mkdirSync(src, { recursive: true });
      writeFileSync(join(src, "file.txt"), "new-version");

      // Also create a legacy static backup directory to ensure it gets cleaned up
      const legacyBackup = `${dst}.backup`;
      mkdirSync(legacyBackup, { recursive: true });
      writeFileSync(join(legacyBackup, "file.txt"), "legacy");

      await replaceDirAtomically(src, dst);

      expect(existsSync(src)).toBe(false);
      expect(existsSync(dst)).toBe(true);
      expect(readFileSync(join(dst, "file.txt"), "utf8")).toBe("new-version");

      // Verify no backup directories remain
      const entries = readdirSync(root);
      expect(entries).toEqual(["my-package"]);
    });
  });

  test("replaceDirAtomically restores previous content on replacement failure", async () => {
    await withTempDir(async (root) => {
      const dst = join(root, "my-package");
      const nonExistentSrc = join(root, "non-existent-src");
      mkdirSync(dst, { recursive: true });
      writeFileSync(join(dst, "file.txt"), "preserved-content");

      await assert.rejects(async () => replaceDirAtomically(nonExistentSrc, dst));

      expect(existsSync(dst)).toBe(true);
      expect(readFileSync(join(dst, "file.txt"), "utf8")).toBe("preserved-content");

      // Verify backup was restored and not left behind
      const entries = readdirSync(root);
      expect(entries).toEqual(["my-package"]);
    });
  });
});
