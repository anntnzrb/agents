import { describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { clonePackageWithRunner } from "@packages/source.ts";

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
});
