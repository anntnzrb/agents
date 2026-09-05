import { describe, expect, test } from "bun:test";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const SYNC_ROOT = resolve(import.meta.dir, "..");

function withTempDir<T>(fn: (root: string) => T | Promise<T>): Promise<T> {
  const root = mkdtempSync(join(tmpdir(), "extensions-install-test-"));
  return Promise.resolve(fn(root)).finally(() => {
    rmSync(root, { recursive: true, force: true });
  });
}

function writeExecutable(filePath: string, content: string): void {
  writeFileSync(filePath, content, "utf8");
  chmodSync(filePath, 0o755);
}

describe("extensions/install.ts", () => {
  test("runs bun install once when node_modules exists, package.json changed, and a new dependency was added", async () => {
    await withTempDir(async (root) => {
      const bin = join(root, "bin");
      mkdirSync(bin, { recursive: true });
      const log = join(root, "installs.log");
      const fakeBun = join(bin, "bun");

      writeExecutable(
        fakeBun,
        `#!/bin/sh
if [ "$1" = "install" ]; then
  echo "$PWD $*" >> "${log}"
  exit 0
fi
echo "unexpected $*" >&2
exit 1
`,
      );

      const ext = join(root, "ext");
      mkdirSync(ext, { recursive: true });
      mkdirSync(join(ext, "node_modules"), { recursive: true });
      writeFileSync(
        join(ext, "package.json"),
        `${JSON.stringify({ name: "ext", dependencies: { chalk: "^5" } })}\n`,
      );

      const proc = Bun.spawnSync(
        [
          process.execPath,
          "-e",
          `import { installExtensionDeps } from "@extensions/install.ts";
const ok = await installExtensionDeps(${JSON.stringify(root)}, ${JSON.stringify(root)}, 5000);
process.exit(ok ? 0 : 1);`,
        ],
        {
          cwd: SYNC_ROOT,
          env: {
            ...process.env,
            PATH: `${bin}:${process.env["PATH"] ?? ""}`,
          },
        },
      );
      expect(proc.exitCode).toBe(0);

      const calls = readFileSync(log, "utf8")
        .split("\n")
        .filter((line) => line.length > 0);
      expect(calls.length).toBe(1);
      expect(calls[0]).toContain(`${ext} install`);
    });
  });
});
