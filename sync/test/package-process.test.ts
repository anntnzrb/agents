import { describe, expect, test } from "bun:test";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { installPackageDeps } from "@packages/process.ts";
import { packageIsHealthy } from "@packages/validate.ts";

function withTempDir<T>(fn: (root: string) => T | Promise<T>): Promise<T> {
  const root = mkdtempSync(join(tmpdir(), "package-process-test-"));
  return Promise.resolve(fn(root)).finally(() => {
    rmSync(root, { recursive: true, force: true });
  });
}

function writeExecutable(filePath: string, content: string): void {
  writeFileSync(filePath, content, "utf8");
  chmodSync(filePath, 0o755);
}

describe("packages/process.ts", () => {
  test("manifestless conventional package with no imports needs no install", async () => {
    await withTempDir(async (root) => {
      mkdirSync(join(root, "skills", "sub"), { recursive: true });
      writeFileSync(join(root, "skills", "sub", "noop.ts"), "const x = 1;\n");
      expect(await installPackageDeps(root, 5000)).toBe(true);
      expect(packageIsHealthy(root)).toBe(true);
    });
  });

  test("manifestless conventional package triggers one fake bun add for missing import", async () => {
    await withTempDir(async (root) => {
      const bin = join(root, "bin");
      mkdirSync(bin, { recursive: true });
      const log = join(root, "bun.log");
      const fakeBun = join(bin, "bun");

      writeExecutable(
        fakeBun,
        `#!/bin/sh
if [ "$1" = "add" ] && [ "$2" = "--no-save" ]; then
  mkdir -p "node_modules/$3"
  echo "$PWD $*" >> "${log}"
  exit 0
fi
echo "unexpected $*" >&2
exit 1
`,
      );

      const originalPath = process.env["PATH"];
      process.env["PATH"] = `${bin}:${originalPath ?? ""}`;
      try {
        mkdirSync(join(root, "skills"), { recursive: true });
        writeFileSync(join(root, "skills", "main.ts"), 'import "some-pkg";\n');
        expect(await installPackageDeps(root, 5000)).toBe(true);

        const calls = readFileSync(log, "utf8")
          .split("\n")
          .filter((line) => line.length > 0);
        expect(calls.length).toBe(1);
        expect(calls[0]).toContain("add --no-save some-pkg");
        expect(packageIsHealthy(root)).toBe(true);
      } finally {
        process.env["PATH"] = originalPath ?? "";
      }
    });
  });
});
