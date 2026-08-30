import { describe, expect, test } from "bun:test";
import {
  chmodSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { packageCacheDir, patchRuntimeSettings } from "@packages/index.ts";

function withTempDir<T>(fn: (root: string) => T | Promise<T>): Promise<T> {
  const root = mkdtempSync(join(tmpdir(), "packages-index-test-"));
  return Promise.resolve(fn(root)).finally(() => {
    rmSync(root, { recursive: true, force: true });
  });
}

describe("packages/index.ts", () => {
  test("patchRuntimeSettings replaces a symlink with a regular file and preserves the external target", async () => {
    await withTempDir(async (root) => {
      const cacheRoot = join(root, "cache");
      mkdirSync(cacheRoot, { recursive: true });
      const source = "https://github.com/owner/repo";
      const expected = packageCacheDir(cacheRoot, source);

      const external = join(root, "external-settings.json");
      const original = '{"theme":"dark","packages":[]}\n';
      writeFileSync(external, original, "utf8");

      const settingsPath = join(root, "settings.json");
      symlinkSync(external, settingsPath);

      patchRuntimeSettings(settingsPath, [expected]);

      const settingsMeta = lstatSync(settingsPath);
      expect(settingsMeta.isFile()).toBe(true);
      expect(settingsMeta.isSymbolicLink()).toBe(false);
      expect(readFileSync(external, "utf8")).toBe(original);

      const parsed = JSON.parse(readFileSync(settingsPath, "utf8")) as {
        theme?: string;
        packages?: string[];
      };
      expect(parsed.packages).toEqual([expected]);
      expect(parsed.theme).toBe("dark");
    });
  });

  test("patchRuntimeSettings preserves the mode of an existing regular file", async () => {
    await withTempDir(async (root) => {
      const settingsPath = join(root, "settings.json");
      writeFileSync(settingsPath, "{}", "utf8");
      chmodSync(settingsPath, 0o644);

      patchRuntimeSettings(settingsPath, []);

      const metadata = lstatSync(settingsPath);
      expect(metadata.isFile()).toBe(true);
      expect(metadata.mode & 0o777).toBe(0o644);
    });
  });
});
