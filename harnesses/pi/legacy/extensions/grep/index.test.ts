import assert from "node:assert/strict";
import test from "node:test";

import {
  balanceMatchesByFile,
  normalizeOffset,
  normalizeOutputMode,
  normalizeTimeout,
  resolveTypeFilter,
} from "./logic.js";
import { __test as ripgrepTest } from "./ripgrep.js";

test("normalizeOffset validates non-negative integers", () => {
  assert.equal(normalizeOffset(undefined), 0);
  assert.equal(normalizeOffset(2.9), 2);
  assert.throws(() => normalizeOffset(-1), /non-negative/);
});

test("normalizeTimeout validates positive values with default", () => {
  assert.equal(normalizeTimeout(undefined), 5000);
  assert.equal(normalizeTimeout(99.9), 99);
  assert.throws(() => normalizeTimeout(0), /positive number/);
  assert.throws(() => normalizeTimeout(Number.NaN), /positive number/);
});

test("normalizeOutputMode validates supported modes", () => {
  assert.equal(normalizeOutputMode(undefined), "content");
  assert.equal(normalizeOutputMode(""), "content");
  assert.equal(normalizeOutputMode("files_with_matches"), "files_with_matches");
  assert.equal(normalizeOutputMode("count"), "count");
  assert.throws(() => normalizeOutputMode("files"), /outputMode/);
});

test("resolveTypeFilter validates supported types", () => {
  const tsFilter = resolveTypeFilter("typescript");
  assert.ok(tsFilter);
  assert.equal(tsFilter?.key, "ts");
  assert.equal(tsFilter?.predicate("/tmp/a.ts"), true);
  assert.equal(tsFilter?.predicate("/tmp/a.py"), false);
  assert.throws(() => resolveTypeFilter("unknown-type"), /Unknown grep type/);
});

test("normalizeRipgrepGlob preserves basename globs and scopes slash globs to any depth", () => {
  assert.equal(ripgrepTest.normalizeRipgrepGlob("*.ts"), "*.ts");
  assert.equal(ripgrepTest.normalizeRipgrepGlob("src/*.ts"), "**/src/*.ts");
  assert.equal(ripgrepTest.normalizeRipgrepGlob("**/src/*.ts"), "**/src/*.ts");
  assert.equal(ripgrepTest.normalizeRipgrepGlob("/tmp/*.ts"), "/tmp/*.ts");
});

test("buildRipgrepCommonArgs excludes git internals unless explicit glob owns filtering", () => {
  assert.ok(
    ripgrepTest
      .buildRipgrepCommonArgs({
        glob: undefined,
        typeFilter: null,
        ignoreCase: false,
        literal: false,
        pcre2: false,
        useGitignore: true,
      })
      .includes("!**/.git/**"),
  );
  assert.equal(
    ripgrepTest
      .buildRipgrepCommonArgs({
        glob: "*.ts",
        typeFilter: null,
        ignoreCase: false,
        literal: false,
        pcre2: false,
        useGitignore: true,
      })
      .includes("!**/.git/**"),
    false,
  );
});

test("buildRipgrepCommonArgs enables PCRE2 unless literal mode owns matching", () => {
  assert.ok(
    ripgrepTest
      .buildRipgrepCommonArgs({
        glob: undefined,
        typeFilter: null,
        ignoreCase: false,
        literal: false,
        pcre2: true,
        useGitignore: true,
      })
      .includes("--pcre2"),
  );
  assert.equal(
    ripgrepTest
      .buildRipgrepCommonArgs({
        glob: undefined,
        typeFilter: null,
        ignoreCase: false,
        literal: true,
        pcre2: true,
        useGitignore: true,
      })
      .includes("--pcre2"),
    false,
  );
});

test("balanceMatchesByFile interleaves files round-robin", () => {
  const ordered = balanceMatchesByFile([
    { absolutePath: "/a", displayPath: "a.ts", lineNumber: 1, lineText: "a1" },
    { absolutePath: "/a", displayPath: "a.ts", lineNumber: 2, lineText: "a2" },
    { absolutePath: "/b", displayPath: "b.ts", lineNumber: 1, lineText: "b1" },
  ]);
  assert.deepEqual(
    ordered.map((entry) => `${entry.displayPath}:${entry.lineNumber}`),
    ["a.ts:1", "b.ts:1", "a.ts:2"],
  );
});
