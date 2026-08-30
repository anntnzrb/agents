import { describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  extractImportSpecifiers,
  missingPackageRoots,
  packageIsHealthy,
} from "@packages/validate.ts";

function withTempDir<T>(fn: (root: string) => T | Promise<T>): Promise<T> {
  const root = mkdtempSync(join(tmpdir(), "package-validate-test-"));
  return Promise.resolve(fn(root)).finally(() => {
    rmSync(root, { recursive: true, force: true });
  });
}

const fixture = String.raw`// import "fake-line";
/* import "fake-block"; */
const a = "import \"x\"";
import chalk from "chalk";
import { Foo } from "@scope/pkg/bar";
import type { Baz } from "typepkg";
export { foo } from "somepkg";
const x = require("required");
const y = import("dynamic");
import ".";
import "node:fs";
import "bun:sqlite";
import "data:base64,abc";
`;

describe("packages/validate.ts", () => {
  test("extractImportSpecifiers ignores comments and strings", () => {
    const specifiers = extractImportSpecifiers(fixture);
    expect(specifiers).toContain("chalk");
    expect(specifiers).toContain("@scope/pkg/bar");
    expect(specifiers).toContain("somepkg");
    expect(specifiers).toContain("required");
    expect(specifiers).toContain("dynamic");
    expect(specifiers).toContain(".");
    expect(specifiers).toContain("node:fs");
    expect(specifiers).toContain("bun:sqlite");
    expect(specifiers).toContain("data:base64,abc");
    expect(specifiers).not.toContain("fake-line");
    expect(specifiers).not.toContain("fake-block");
    expect(specifiers).not.toContain("x");
    expect(specifiers).not.toContain("typepkg");
  });

  test("missingPackageRoots reports only real package roots", async () => {
    await withTempDir(async (root) => {
      mkdirSync(join(root, "skills"), { recursive: true });
      writeFileSync(
        join(root, "skills", "main.ts"),
        'import chalk from "chalk";\nimport fs from "node:fs";\nimport "./local";\nconst x = require("some-pkg");\n',
      );
      expect(missingPackageRoots(root)).toEqual(["chalk", "some-pkg"]);

      mkdirSync(join(root, "node_modules", "chalk"), { recursive: true });
      mkdirSync(join(root, "node_modules", "some-pkg"), { recursive: true });
      expect(missingPackageRoots(root)).toEqual([]);
      expect(packageIsHealthy(root)).toBe(true);
    });
  });
});
