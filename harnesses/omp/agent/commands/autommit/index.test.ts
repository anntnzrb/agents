import { describe, expect, test } from "bun:test";
import { access, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { consumeCompletedReceipt, emitTrace, preparedCommitTreeMatchesIndex, selectPatch, unquoteGitPath } from "./index";
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
