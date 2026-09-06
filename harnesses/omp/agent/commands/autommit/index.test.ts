import { describe, expect, test } from "bun:test";
import { access, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { consumeCompletedReceipt, describeOperationLock, emitTrace, preparedCommitTreeMatchesIndex, selectPatch, unquoteGitPath, validateHunkCoverage } from "./index";
import { readReceipt, writeReceipt } from "./transaction";


const renamePatch = [
  "diff --git a/old/path.txt b/new/path.txt",
  "similarity index 100%",
  "rename from old/path.txt",
  "rename to new/path.txt",
  "",
].join("\n");

const file = {
  filename: "new/path.txt",
  content: renamePatch,
  additions: 0,
  deletions: 0,
  isBinary: false,
} satisfies Parameters<typeof selectPatch>[0];

const internals = {
  parseFileHunks: () => ({
    filename: file.filename,
    isBinary: file.isBinary,
    hunks: [],
  }),
} as Parameters<typeof selectPatch>[2];

describe("consumeCompletedReceipt", () => {
  test("consumes completed receipts across branch and rewritten-tip changes", async () => {
    const commonDir = await mkdtemp(join(tmpdir(), "autommit-index-"));
    const receiptPath = join(commonDir, "autommit", "receipt.json");
    const committedReceipt = {
      version: 1 as const,
      state: "committed" as const,
      ref: "refs/heads/re-written",
      before: "1111111111111111111111111111111111111111",
      after: "9999999999999999999999999999999999999999",
      indexTree: "3333333333333333333333333333333333333333",
    };
    const preparedReceipt = { ...committedReceipt, state: "prepared" as const };
    try {
      await writeReceipt(commonDir, committedReceipt);
      expect(await consumeCompletedReceipt(commonDir, committedReceipt)).toBeNull();
      expect(await readReceipt(commonDir)).toBeNull();
      await expect(access(receiptPath)).rejects.toThrow();

      await writeReceipt(commonDir, preparedReceipt);
      expect(await consumeCompletedReceipt(commonDir, preparedReceipt)).toBe(preparedReceipt);
      expect(await readReceipt(commonDir)).toEqual(preparedReceipt);
    } finally {
      await rm(commonDir, { recursive: true, force: true });
    }
  });
});

describe("selectPatch", () => {
  test("preserves metadata-only rename patches for whole-file selection", () => {
    expect(selectPatch(file, { path: file.filename, kind: "all" }, internals)).toBe(renamePatch);
  });

  test("preserves exact file diff content for whole-file selection with hunks", () => {
    const fileWithHunks = {
      filename: "src/app.ts",
      content: [
        "diff --git a/src/app.ts b/src/app.ts",
        "index 1234567..89abcdef 100644",
        "--- a/src/app.ts",
        "+++ b/src/app.ts",
        "@@ -1,3 +1,3 @@",
        " const a = 1;",
        "-const b = 2;",
        "+const b = 3;",
        " const c = 4;",
      ].join("\n"),
      additions: 1,
      deletions: 1,
      isBinary: false,
    };
    expect(selectPatch(fileWithHunks, { path: fileWithHunks.filename, kind: "all" }, internals)).toBe(fileWithHunks.content);
  });

  test("rejects partial selection of metadata-only rename patches", () => {
    expect(() => selectPatch(file, { path: file.filename, kind: "indices", indices: [1] }, internals)).toThrow(
      "Cannot partially select renamed file new/path.txt; entire file change must be committed together.",
    );
  });
});

describe("prepared commit tree verification", () => {
  test("accepts the committed tree but rejects post-commit index drift", () => {
    const expectedIndexTree = "staged-index-tree";
    const preparedCommitTree = expectedIndexTree;
    const postCommitIndexTree = "post-commit-index-tree";

    expect(preparedCommitTreeMatchesIndex(preparedCommitTree, expectedIndexTree)).toBe(true);
    expect(preparedCommitTreeMatchesIndex(postCommitIndexTree, expectedIndexTree)).toBe(false);
  });

  test("detects mismatch when prepared commit tree diverges from staged index", () => {
    const expectedIndexTree = "a1b2c3d4e5f6";
    const preparedCommitTree = "f6e5d4c3b2a1";
    expect(preparedCommitTreeMatchesIndex(preparedCommitTree, expectedIndexTree)).toBe(false);
  });
});

describe("unquoteGitPath", () => {
  test("decodes octal-escaped UTF-8 paths from Git C-quoting", () => {
    const octalQuoted = '"\\321\\202\\320\\265\\321\\201\\321\\202 \\321\\204\\320\\260\\320\\271\\320\\273 1.txt"';
    expect(unquoteGitPath(octalQuoted)).toBe("тест файл 1.txt");
  });

  test("decodes special escapes and escaped quotes", () => {
    expect(unquoteGitPath('"path/with/\\"quotes\\".txt"')).toBe('path/with/"quotes".txt');
    expect(unquoteGitPath('"path/with/\\ttab.txt"')).toBe("path/with/\ttab.txt");
    expect(unquoteGitPath('"path/with/\\nnewline.txt"')).toBe("path/with/\nnewline.txt");
    expect(unquoteGitPath('"path\\\\with\\\\backslash.txt"')).toBe("path\\with\\backslash.txt");
  });

  test("passes unquoted paths through unchanged", () => {
    expect(unquoteGitPath("plain/path.txt")).toBe("plain/path.txt");
    expect(unquoteGitPath("тест.txt")).toBe("тест.txt");
  });
});

describe("emitTrace", () => {
  test("does nothing when debug is disabled", () => {
    expect(() => emitTrace(false, "test_event")).not.toThrow();
  });

  test("emits JSON trace when debug is enabled", () => {
    const writes: string[] = [];
    const originalWrite = process.stderr.write;
    process.stderr.write = ((chunk: string) => {
      writes.push(chunk);
      return true;
    }) as typeof process.stderr.write;
    try {
      emitTrace(true, "test_event", { foo: "bar" });
      expect(writes.length).toBe(1);
      const parsed = JSON.parse(writes[0]);
      expect(parsed.event).toBe("test_event");
      expect(parsed.foo).toBe("bar");
      expect(typeof parsed.timestamp).toBe("string");
    } finally {
      process.stderr.write = originalWrite;
    }
  });
});

describe("validateHunkCoverage", () => {
  const parsedFiles = new Map([
    ["a.txt", {
      hunks: [
        { index: 0, newStart: 10, newLines: 5, content: "@@ -10,5 +10,5 @@" },
        { index: 1, newStart: 30, newLines: 4, content: "@@ -30,4 +30,4 @@" },
      ],
    }],
  ]) as unknown as Parameters<typeof validateHunkCoverage>[2];
  const commit = (summary: string, changes: { path: string; kind: "all" | "indices" | "lines"; indices?: number[]; start?: number; end?: number }[]) => ({
    changes,
    summary,
  }) as unknown as Parameters<typeof validateHunkCoverage>[1][number];

  test("accepts disjoint hunk indices of one file split across commits", () => {
    const errors = validateHunkCoverage(
      ["a.txt"],
      [
        commit("first", [{ path: "a.txt", kind: "indices", indices: [1] }]),
        commit("second", [{ path: "a.txt", kind: "indices", indices: [2] }]),
      ],
      parsedFiles,
    );
    expect(errors).toEqual([]);
  });

  test("accepts disjoint line ranges of one file split across commits", () => {
    const errors = validateHunkCoverage(
      ["a.txt"],
      [
        commit("first", [{ path: "a.txt", kind: "lines", start: 10, end: 14 }]),
        commit("second", [{ path: "a.txt", kind: "lines", start: 30, end: 33 }]),
      ],
      parsedFiles,
    );
    expect(errors).toEqual([]);
  });

  test("rejects overlapping selections of one file across commits", () => {
    const errors = validateHunkCoverage(
      ["a.txt"],
      [
        commit("first", [{ path: "a.txt", kind: "indices", indices: [1] }]),
        commit("second", [{ path: "a.txt", kind: "indices", indices: [1, 2] }]),
      ],
      parsedFiles,
    );
    expect(errors.some(error => error.includes("Overlapping hunk selections"))).toBe(true);
  });

  test("rejects split plans missing staged hunks", () => {
    const errors = validateHunkCoverage(
      ["a.txt"],
      [commit("first", [{ path: "a.txt", kind: "indices", indices: [1] }])],
      parsedFiles,
    );
    expect(errors.some(error => error.includes("Staged hunk missing"))).toBe(true);
  });
});

describe("describeOperationLock", () => {
  const writeLock = async (dir: string, content: string): Promise<void> => {
    await mkdir(join(dir, "autommit"), { recursive: true });
    await writeFile(join(dir, "autommit", "operation.lock"), content, "utf8");
  };

  test("returns undefined when no lock exists", async () => {
    const dir = await mkdtemp(join(tmpdir(), "autommit-lock-"));
    try {
      expect(await describeOperationLock(dir)).toBeUndefined();
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });

  test("reports a stale lock for a dead PID", async () => {
    const dir = await mkdtemp(join(tmpdir(), "autommit-lock-"));
    try {
      await writeLock(dir, `${JSON.stringify({ pid: 2 ** 30, token: "test" })}\n`);
      const hint = await describeOperationLock(dir);
      expect(hint).toContain("stale");
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });

  test("reports a live lock for the current process", async () => {
    const dir = await mkdtemp(join(tmpdir(), "autommit-lock-"));
    try {
      await writeLock(dir, `${JSON.stringify({ pid: process.pid, token: "test" })}\n`);
      const hint = await describeOperationLock(dir);
      expect(hint).toContain("live");
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });
});
