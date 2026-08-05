import { describe, expect, test } from "bun:test";
import { selectPatch } from "./index";

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

describe("selectPatch", () => {
  test("preserves metadata-only rename patches for whole-file selection", () => {
    expect(selectPatch(file, { type: "all" }, internals)).toBe(renamePatch);
  });

  test("rejects partial selection of metadata-only rename patches", () => {
    expect(() => selectPatch(file, { type: "indices", indices: [1] }, internals)).toThrow(
      "No changes selected for new/path.txt.",
    );
  });
});
