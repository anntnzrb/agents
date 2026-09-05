import { describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildHarness } from "@core/harness.ts";
import { HARNESS_ADAPTERS } from "@core/harness-adapters.ts";
import {
  fingerprintTree,
  prepareExtensionHookState,
  recordExtensionHookState,
} from "@core/hook-state.ts";

const makeRoot = (): string => mkdtempSync(join(tmpdir(), "hook-state-test-"));

describe("fingerprintTree", () => {
  test("is stable for an unchanged source tree", () => {
    const root = makeRoot();
    try {
      mkdirSync(join(root, "src"), { recursive: true });
      writeFileSync(join(root, "src", "a.ts"), "a");
      writeFileSync(join(root, "package.json"), "{}");
      expect(fingerprintTree(root)).toBe(fingerprintTree(root));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("changes when file content changes", () => {
    const root = makeRoot();
    try {
      mkdirSync(join(root, "src"), { recursive: true });
      writeFileSync(join(root, "src", "a.ts"), "a");
      const first = fingerprintTree(root);
      writeFileSync(join(root, "src", "a.ts"), "b");
      const second = fingerprintTree(root);
      expect(first).not.toBe(second);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("ignores python cache directories and compiled files", () => {
    const root = makeRoot();
    try {
      mkdirSync(join(root, "src", "__pycache__"), { recursive: true });
      writeFileSync(join(root, "src", "a.py"), "print(1)");
      writeFileSync(join(root, "src", "__pycache__", "a.cpython-312.pyc"), "bytecode");
      writeFileSync(join(root, "src", "compiled.pyo"), "bytecode");
      const baseline = fingerprintTree(root);

      writeFileSync(join(root, "src", "__pycache__", "a.cpython-312.pyc"), "mutated");
      writeFileSync(join(root, "src", "compiled.pyo"), "mutated");
      expect(fingerprintTree(root)).toBe(baseline);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

describe("prepareExtensionHookState", () => {
  test("produces exact serialized { fingerprint, generatedEntries }", () => {
    const sourceRoot = makeRoot();
    const home = makeRoot();
    try {
      mkdirSync(join(sourceRoot, "src"), { recursive: true });
      writeFileSync(join(sourceRoot, "src", "a.ts"), "a");
      writeFileSync(join(sourceRoot, "package.json"), "{}");
      const managedStateHome = join(home, ".local", "share", "agents", "sync-managed");
      mkdirSync(managedStateHome, { recursive: true });
      const adapter = HARNESS_ADAPTERS.find((a) => a.id === "opencode")!;
      const harness = buildHarness({
        ...adapter,
        id: adapter.id,
        sourceName: adapter.id,
        home,
      });
      const statePath = join(managedStateHome, "opencode.extension-deps.json");
      const fingerprint = fingerprintTree(sourceRoot);
      const generatedEntries = ["package.json"];
      writeFileSync(statePath, JSON.stringify({ fingerprint, generatedEntries }));
      writeFileSync(join(home, "package.json"), "{}");
      const hook = {
        kind: "ExtensionDeps" as const,
        harness,
        jobRoot: home,
        root: home,
        sourceRoot,
        relativeRoot: "",
        statePath,
        timeoutMs: 1000,
      };
      const state = prepareExtensionHookState(hook);
      expect(state.shouldSkip).toBe(true);
      expect(state.fingerprint).toBe(fingerprint);
      expect(state.generatedEntries).toEqual(generatedEntries);
      expect(state.preservePaths).toEqual(["package.json"]);
    } finally {
      rmSync(sourceRoot, { recursive: true, force: true });
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("uses an empty relativeRoot without a ./ prefix", () => {
    const sourceRoot = makeRoot();
    const home = makeRoot();
    try {
      mkdirSync(join(sourceRoot, "src"), { recursive: true });
      writeFileSync(join(sourceRoot, "src", "a.ts"), "a");
      writeFileSync(join(sourceRoot, "package.json"), "{}");
      const managedStateHome = join(home, ".local", "share", "agents", "sync-managed");
      mkdirSync(managedStateHome, { recursive: true });
      const adapter = HARNESS_ADAPTERS.find((a) => a.id === "opencode")!;
      const harness = buildHarness({
        ...adapter,
        id: adapter.id,
        sourceName: adapter.id,
        home,
      });
      const statePath = join(managedStateHome, "opencode.extension-deps.json");
      const fingerprint = fingerprintTree(sourceRoot);
      writeFileSync(statePath, JSON.stringify({ fingerprint, generatedEntries: ["package.json"] }));
      writeFileSync(join(home, "package.json"), "{}");
      const hook = {
        kind: "ExtensionDeps" as const,
        harness,
        jobRoot: home,
        root: home,
        sourceRoot,
        relativeRoot: "",
        statePath,
        timeoutMs: 1000,
      };
      const state = prepareExtensionHookState(hook);
      expect(state.shouldSkip).toBe(true);
      expect(state.preservePaths).not.toContain("./package.json");
      expect(state.preservePaths).toContain("package.json");
    } finally {
      rmSync(sourceRoot, { recursive: true, force: true });
      rmSync(home, { recursive: true, force: true });
    }
  });
  test("records and preserves nested package generated entries (e.g. skills)", () => {
    const sourceRoot = makeRoot();
    const home = makeRoot();
    try {
      mkdirSync(join(sourceRoot, "skill-a"), { recursive: true });
      writeFileSync(join(sourceRoot, "skill-a", "package.json"), "{}");
      mkdirSync(join(home, "skill-a", "node_modules", "dep"), { recursive: true });
      writeFileSync(join(home, "skill-a", "package.json"), "{}");
      writeFileSync(join(home, "skill-a", "bun.lock"), "");

      const managedStateHome = join(home, ".local", "share", "agents", "sync-managed");
      mkdirSync(managedStateHome, { recursive: true });
      const adapter = HARNESS_ADAPTERS.find((a) => a.id === "omp")!;
      const harness = buildHarness({
        ...adapter,
        id: adapter.id,
        sourceName: adapter.id,
        home,
      });
      const statePath = join(managedStateHome, "omp.skills-deps.json");
      const hook = {
        kind: "ExtensionDeps" as const,
        harness,
        jobRoot: join(home, "skills"),
        root: home,
        sourceRoot,
        relativeRoot: "",
        statePath,
        timeoutMs: 1000,
      };

      const prepared = prepareExtensionHookState(hook);
      expect(prepared.shouldSkip).toBe(false);

      recordExtensionHookState(hook, prepared);

      const updatedState = prepareExtensionHookState(hook);
      expect(updatedState.shouldSkip).toBe(true);
      expect(updatedState.preservePaths).toContain("skill-a/node_modules");
      expect(updatedState.preservePaths).toContain("skill-a/bun.lock");
      expect(updatedState.preservePaths).toContain("skill-a/package.json");
    } finally {
      rmSync(sourceRoot, { recursive: true, force: true });
      rmSync(home, { recursive: true, force: true });
    }
  });
});
