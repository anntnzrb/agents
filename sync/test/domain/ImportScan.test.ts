import { expect, test } from "bun:test"

import {
  extractImportSpecifiers,
  isValidPackageRoot,
  missingPackageRoots,
  packageRootFromSpecifier,
} from "#domain/ImportScan"

test("extracts runtime imports while ignoring comments, strings and type-only declarations", () => {
  const source = `
      // import "fake";
      /* require("fake2") */
      const text = 'import "fake3"';
      const template = \`import "fake4" \${(() => require("inside"))()}\`;
      import x from "chalk";
      import type { A } from "types";
      import type from "runtime-type";
      import "side-effect";
      export { x } from "exported";
      export type { X } from "export-types";
      const a = require("required");
      const b = import("dynamic");
      obj.require("property"); obj.import("property2");
    `
  expect(extractImportSpecifiers(source)).toEqual([
    "inside",
    "chalk",
    "runtime-type",
    "side-effect",
    "exported",
    "required",
    "dynamic",
  ])
})

test("distinguishes regex literals from division and scans nested template expressions", () => {
  const source = `const a = /require\\("phantom"\\)/g;
    const b = /[/]/; const c = !/import\\("fake"\\)/.test(s);
    const d = 5 / require("after-div");
    const e = \`outer \${{x: \`nested \${import("nested")}\`}.x}\`;
    require("last");`
  expect(extractImportSpecifiers(source)).toEqual(["after-div", "nested", "last"])
})

test("normalizes and filters package roots and returns missing roots sorted and unique", () => {
  expect(packageRootFromSpecifier(" @scope/pkg/deep ")).toBe("@scope/pkg")
  for (const value of [
    "",
    ".",
    "../foo",
    "/foo",
    "node:fs",
    "bun",
    "bun:sqlite",
    "data:x",
    "@scope",
    "@scope/",
    "bad name",
  ]) {
    expect(packageRootFromSpecifier(value)).toBeUndefined()
  }
  expect(isValidPackageRoot("@scope/name-1")).toBe(true)
  expect(isValidPackageRoot("@scope/")).toBe(false)
  expect(
    missingPackageRoots(
      [
        'import "z/deep"; import "fs"; import "node:path"; import "@scope/pkg/a";',
        'require("z"); require("installed"); import "./local";',
      ],
      (root) => root === "installed",
    ),
  ).toEqual(["@scope/pkg", "z"])
})
