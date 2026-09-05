import { describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
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

  test("refuses source directory symlinks with diagnostic error", () => {
    const root = makeRoot();
    try {
      mkdirSync(join(root, "target_dir"), { recursive: true });
      writeFileSync(join(root, "target_dir", "file.txt"), "hello");
      symlinkSync(join(root, "target_dir"), join(root, "link_dir"));
      expect(() => fingerprintTree(root)).toThrow(
        `refusing source directory symlink: ${join(root, "link_dir")}`,
      );
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("rejects recursive symlink cycles before unbounded recursion", () => {
    const root = makeRoot();
    try {
      mkdirSync(join(root, "sub"), { recursive: true });
      symlinkSync(root, join(root, "sub", "cycle"));
      expect(() => fingerprintTree(root)).toThrow(
        `refusing source directory symlink: ${join(root, "sub", "cycle")}`,
      );
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("rejects symlink loop cycles before unbounded recursion", () => {
    const root = makeRoot();
    try {
      symlinkSync(join(root, "link_b"), join(root, "link_a"));
      symlinkSync(join(root, "link_a"), join(root, "link_b"));
      expect(() => fingerprintTree(root)).toThrow();
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("records broken symlinks without failing", () => {
    const root = makeRoot();
    try {
      symlinkSync(join(root, "nonexistent"), join(root, "broken_link"));
      const fp1 = fingerprintTree(root);
      expect(typeof fp1).toBe("string");
      expect(fp1.length).toBeGreaterThan(0);
      expect(fingerprintTree(root)).toBe(fp1);

      symlinkSync(join(root, "nonexistent2"), join(root, "broken_link_2"));
      const fp2 = fingerprintTree(root);
      expect(fp2).not.toBe(fp1);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("regular files and normal subdirectories continue to fingerprint identically", () => {
    const root1 = makeRoot();
    const root2 = makeRoot();
    try {
      for (const r of [root1, root2]) {
        mkdirSync(join(r, "src", "nested"), { recursive: true });
        writeFileSync(join(r, "src", "index.ts"), "export const x = 1;");
        writeFileSync(join(r, "src", "nested", "util.ts"), "export const util = true;");
        writeFileSync(join(r, "package.json"), '{"name":"test"}');
      }
      expect(fingerprintTree(root1)).toBe(fingerprintTree(root2));
    } finally {
      rmSync(root1, { recursive: true, force: true });
      rmSync(root2, { recursive: true, force: true });
    }
  });

  test("fingerprints symlinks to regular files", () => {
    const root = makeRoot();
    try {
      writeFileSync(join(root, "target.txt"), "target content");
      symlinkSync(join(root, "target.txt"), join(root, "link.txt"));
      const fp = fingerprintTree(root);
      expect(typeof fp).toBe("string");
      expect(fingerprintTree(root)).toBe(fp);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("sorts directory entries with mixed-case and non-ASCII names in deterministic code-point order", () => {
    const root = makeRoot();
    try {
      for (const name of ["_x", "a", "B", "ä", "z"]) {
        writeFileSync(join(root, name), `content of ${name}`);
      }
      mkdirSync(join(root, "Sub_C"));
      writeFileSync(join(root, "Sub_C", "file.txt"), "sub C");
      mkdirSync(join(root, "sub_b"));
      writeFileSync(join(root, "sub_b", "file.txt"), "sub b");
      mkdirSync(join(root, "sub_ä"));
      writeFileSync(join(root, "sub_ä", "file.txt"), "sub ä");

      const hash = new Bun.CryptoHasher("sha256");
      // Deterministic Unicode code-point order:
      // "B" (0x42)
      // "Sub_C" (0x53...) -> dir:Sub_C -> file:Sub_C/file.txt
      // "_x" (0x5F)
      // "a" (0x61)
      // "sub_b" (0x73 0x75 0x62 0x5F 0x62) -> dir:sub_b -> file:sub_b/file.txt
      // "sub_ä" (0x73 0x75 0x62 0x5F 0xE4) -> dir:sub_ä -> file:sub_ä/file.txt
      // "z" (0x7A)
      // "ä" (0xE4)
      hash.update("file:B\n");
      hash.update(Buffer.from("content of B"));
      hash.update("\n");

      hash.update("dir:Sub_C\n");
      hash.update("file:Sub_C/file.txt\n");
      hash.update(Buffer.from("sub C"));
      hash.update("\n");

      hash.update("file:_x\n");
      hash.update(Buffer.from("content of _x"));
      hash.update("\n");

      hash.update("file:a\n");
      hash.update(Buffer.from("content of a"));
      hash.update("\n");

      hash.update("dir:sub_b\n");
      hash.update("file:sub_b/file.txt\n");
      hash.update(Buffer.from("sub b"));
      hash.update("\n");

      hash.update("dir:sub_ä\n");
      hash.update("file:sub_ä/file.txt\n");
      hash.update(Buffer.from("sub ä"));
      hash.update("\n");

      hash.update("file:z\n");
      hash.update(Buffer.from("content of z"));
      hash.update("\n");

      hash.update("file:ä\n");
      hash.update(Buffer.from("content of ä"));
      hash.update("\n");

      const expected = hash.digest("hex");
      expect(fingerprintTree(root)).toBe(expected);
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
