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

const fixture = [
  '// import "fake-line";',
  '// require("fake-line-req");',
  '// import("fake-line-dyn");',
  "/*",
  ' * import "fake-block";',
  ' * const r = require("fake-block-req");',
  ' * import("fake-block-dyn");',
  " */",
  'const doubleQuoteStr = "import \\"fake-str\\" require(\\"fake-str-req\\") import(\\"fake-str-dyn\\")";',
  'const singleQuoteStr = \'import "fake-str-single" require("fake-str-single-req") import("fake-str-single-dyn")\';',
  "const templateLiteral = `",
  '  import "fake-tpl-multiline";',
  '  const x = require("fake-tpl-req");',
  '  import("fake-tpl-dyn");',
  "`;",
  "const interpolatedTpl = `outer $" +
    "{\"import \\'fake-in-str\\'\"} $" +
    '{(() => require("real-inside-tpl-expr"))()}`;',
  "",
  'import chalk from "chalk";',
  'import { Foo } from "@scope/pkg/bar";',
  'import type { Baz } from "typepkg";',
  'export { foo } from "somepkg";',
  'export * from "wildcardpkg";',
  'const x = require("required");',
  'const spacedReq = require(  "@scoped/spaced-req"  );',
  'const y = import("dynamic");',
  'const dynScoped = import("@scoped/dynamic");',
  'import ".";',
  'import "./local-file";',
  'import "../parent-file";',
  'import "node:fs";',
  'import "node:path/posix";',
  'import "bun:sqlite";',
  'import "data:base64,abc";',
].join("\n");

describe("packages/validate.ts", () => {
  test("extractImportSpecifiers extracts real imports and ignores comments and string literals", () => {
    const specifiers = extractImportSpecifiers(fixture);

    // Real imports, exports, requires, and dynamic imports
    expect(specifiers).toContain("chalk");
    expect(specifiers).toContain("@scope/pkg/bar");
    expect(specifiers).toContain("somepkg");
    expect(specifiers).toContain("wildcardpkg");
    expect(specifiers).toContain("required");
    expect(specifiers).toContain("@scoped/spaced-req");
    expect(specifiers).toContain("dynamic");
    expect(specifiers).toContain("@scoped/dynamic");
    expect(specifiers).toContain("real-inside-tpl-expr");

    // Relative, builtins, and data URIs are extracted at this stage
    expect(specifiers).toContain(".");
    expect(specifiers).toContain("./local-file");
    expect(specifiers).toContain("../parent-file");
    expect(specifiers).toContain("node:fs");
    expect(specifiers).toContain("node:path/posix");
    expect(specifiers).toContain("bun:sqlite");
    expect(specifiers).toContain("data:base64,abc");

    // Comments must be ignored
    expect(specifiers).not.toContain("fake-line");
    expect(specifiers).not.toContain("fake-line-req");
    expect(specifiers).not.toContain("fake-line-dyn");
    expect(specifiers).not.toContain("fake-block");
    expect(specifiers).not.toContain("fake-block-req");
    expect(specifiers).not.toContain("fake-block-dyn");

    // String and template literals must be ignored
    expect(specifiers).not.toContain("fake-str");
    expect(specifiers).not.toContain("fake-str-req");
    expect(specifiers).not.toContain("fake-str-dyn");
    expect(specifiers).not.toContain("fake-str-single");
    expect(specifiers).not.toContain("fake-str-single-req");
    expect(specifiers).not.toContain("fake-str-single-dyn");
    expect(specifiers).not.toContain("fake-tpl-multiline");
    expect(specifiers).not.toContain("fake-tpl-req");
    expect(specifiers).not.toContain("fake-tpl-dyn");
    expect(specifiers).not.toContain("fake-in-str");

    // Type-only imports are erased during transpilation
    expect(specifiers).not.toContain("typepkg");
  });

  test("missingPackageRoots reports only real package roots and ignores local/builtins/data URIs", async () => {
    await withTempDir(async (root) => {
      mkdirSync(join(root, "skills"), { recursive: true });
      writeFileSync(
        join(root, "skills", "main.ts"),
        [
          'import chalk from "chalk/subpath";',
          'import { helper } from "@scoped/pkg/deep/path";',
          'import fs from "node:fs";',
          'import path from "node:path/posix";',
          'import { Database } from "bun:sqlite";',
          'import "bun";',
          'import "./local";',
          'import "../parent";',
          'import ".";',
          'import "data:text/javascript,console.log(1)";',
          'const x = require("some-pkg");',
        ].join("\n"),
      );
      expect(missingPackageRoots(root)).toEqual(["@scoped/pkg", "chalk", "some-pkg"]);

      mkdirSync(join(root, "node_modules", "@scoped", "pkg"), { recursive: true });
      mkdirSync(join(root, "node_modules", "chalk"), { recursive: true });
      mkdirSync(join(root, "node_modules", "some-pkg"), { recursive: true });
      expect(missingPackageRoots(root)).toEqual([]);
      expect(packageIsHealthy(root)).toBe(true);
    });
  });

  test("extractImportSpecifiers ignores property accesses and handles invalid syntax gracefully", () => {
    const code = [
      'const a = obj.require("ignored-prop-pkg");',
      'const b = myObj.nested.require("ignored-nested-pkg");',
      'const c = require("valid-req-pkg");',
    ].join("\n");
    const specifiers = extractImportSpecifiers(code);
    expect(specifiers).toContain("valid-req-pkg");
    expect(specifiers).not.toContain("ignored-prop-pkg");
    expect(specifiers).not.toContain("ignored-nested-pkg");

    // Invalid syntax should return empty array rather than throwing
    expect(extractImportSpecifiers("const broken = {{{;")).toEqual([]);
  });
});
