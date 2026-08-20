import { describe, expect, test } from "bun:test";
import { access, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { consumeCompletedReceipt, preparedCommitTreeMatchesIndex, selectPatch } from "./index";
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
    expect(selectPatch(file, { type: "all" }, internals)).toBe(renamePatch);
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
    expect(selectPatch(fileWithHunks, { type: "all" }, internals)).toBe(fileWithHunks.content);
  });

  test("rejects partial selection of metadata-only rename patches", () => {
    expect(() => selectPatch(file, { type: "indices", indices: [1] }, internals)).toThrow(
      "No changes selected for new/path.txt.",
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
});
