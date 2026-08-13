import { describe, expect, test } from "bun:test";
import { parseFileDiffs } from "./diff.js";
import {
    buildCommitPatch,
    parseProposalText,
    selectPatch,
    validateProposalCoverage,
} from "./proposal.js";

const stagedDiff = [
    "diff --git a/src/a.ts b/src/a.ts",
    "index 1111111..2222222 100644",
    "--- a/src/a.ts",
    "+++ b/src/a.ts",
    "@@ -1,3 +1,4 @@",
    " one",
    "+two",
    " three",
    "@@ -10,3 +11,4 @@",
    " ten",
    "+eleven",
    " twelve",
    "",
].join("\n");

describe("autommit proposal validation", () => {
    test("normalizes fenced JSON and covers every staged hunk exactly once", () => {
        const proposal = parseProposalText(["```json", JSON.stringify({
            commits: [{
                summary: "Add values",
                changes: [{ path: "src/a.ts", hunks: "all" }],
            }],
        }), "```"].join("\n"));
        expect(validateProposalCoverage(proposal, ["src/a.ts"], parseFileDiffs(stagedDiff))).toEqual([]);
    });

    test("rejects omitted files and overlapping split selections", () => {
        const proposal = parseProposalText(JSON.stringify({
            commits: [
                { summary: "First", changes: [{ path: "src/a.ts", hunks: { type: "indices", indices: [1] } }] },
                { summary: "Second", changes: [{ path: "src/a.ts", hunks: { type: "indices", indices: [1] } }] },
            ],
        }));
        const errors = validateProposalCoverage(proposal, ["src/a.ts", "missing.ts"], parseFileDiffs(stagedDiff));
        expect(errors).toContain("Staged file missing from split plan: missing.ts");
        expect(errors.some(error => error.startsWith("Overlapping hunk selections across commits: src/a.ts"))).toBe(true);
        expect(errors).toContain("Staged hunk missing from split plan: src/a.ts (hunk 2)");
    });

    test("rejects extra keys in the normalized proposal boundary", () => {
        expect(() => parseProposalText(JSON.stringify({
            commits: [{
                summary: "Add values",
                changes: [{
                    path: "src/a.ts",
                    hunks: { type: "all", extra: true },
                }],
            }],
        }))).toThrow(/Invalid autommit proposal/);
    });

    test("selects a hunk while preserving the unified diff header", () => {
        const file = parseFileDiffs(stagedDiff)[0];
        if (!file) throw new Error("test diff did not parse");
        const patch = selectPatch(file, { type: "indices", indices: [2] });
        expect(patch).toContain("diff --git a/src/a.ts b/src/a.ts");
        expect(patch).toContain("@@ -10,3 +11,4 @@");
        expect(patch).not.toContain("@@ -1,3 +1,4 @@");
    });

    test("preserves metadata-only rename patches as whole-file changes", () => {
        const rename = parseFileDiffs([
            "diff --git a/old.txt b/new.txt",
            "similarity index 100%",
            "rename from old.txt",
            "rename to new.txt",
            "",
        ].join("\n"))[0];
        if (!rename) throw new Error("rename diff did not parse");
        expect(rename.filename).toBe("new.txt");
        expect(selectPatch(rename, { type: "all" })).toContain("rename to new.txt");
        expect(() => selectPatch(rename, { type: "indices", indices: [1] })).toThrow();
    });

    test("does not split a file when its contents mention diff headers", () => {
        const diff = [
            "diff --git a/source.ts b/source.ts",
            "index 1111111..2222222 100644",
            "--- a/source.ts",
            "+++ b/source.ts",
            "@@ -1 +1,2 @@",
            "-const oldValue = true;",
            "+const header = \"diff --git a/not-a-file b/not-a-file\";",
            "+const newValue = true;",
            "",
        ].join("\n");
        const files = parseFileDiffs(diff);
        expect(files).toHaveLength(1);
        expect(files[0]?.content).toContain("not-a-file");
    });

    test("parses adjacent tracked and new-file diffs", () => {
        const files = parseFileDiffs([
            stagedDiff.trimEnd(),
            "diff --git a/new.txt b/new.txt",
            "new file mode 100644",
            "index 0000000..1111111",
            "--- /dev/null",
            "+++ b/new.txt",
            "@@ -0,0 +1 @@",
            "+new file",
            "",
        ].join("\n"));
        expect(files.map(file => file.filename)).toEqual(["src/a.ts", "new.txt"]);
    });

    test("builds a patch for each selected change", () => {
        const patch = buildCommitPatch(
            [{ path: "src/a.ts", hunks: { type: "indices", indices: [1] } }],
            stagedDiff,
            stagedDiff,
        );
        expect(patch).toContain("@@ -1,3 +1,4 @@");
        expect(patch).not.toContain("@@ -10,3 +11,4 @@");
    });
});
