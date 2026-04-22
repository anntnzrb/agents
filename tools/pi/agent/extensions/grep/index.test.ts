import assert from "node:assert/strict";
import test from "node:test";

import {
	balanceMatchesByFile,
	normalizeOffset,
	normalizeSearchRoots,
	resolveTypeFilter,
} from "./logic.js";

test("normalizeSearchRoots supports multipath trimming and dedupe", () => {
	const roots = normalizeSearchRoots(undefined, ["apps", "packages", "packages", " libs "]);
	assert.deepEqual(roots, ["apps", "packages", "libs"]);
});

test("normalizeSearchRoots keeps commas literal", () => {
	const roots = normalizeSearchRoots("apps,packages", undefined);
	assert.deepEqual(roots, ["apps,packages"]);
});

test("normalizeSearchRoots rejects path and paths together", () => {
	assert.throws(() => normalizeSearchRoots("src", ["apps"]), /either path or paths/);
});

test("normalizeOffset validates non-negative integers", () => {
	assert.equal(normalizeOffset(undefined), 0);
	assert.equal(normalizeOffset(2.9), 2);
	assert.throws(() => normalizeOffset(-1), /non-negative/);
});

test("resolveTypeFilter validates supported types", () => {
	const tsFilter = resolveTypeFilter("typescript");
	assert.ok(tsFilter);
	assert.equal(tsFilter?.key, "ts");
	assert.equal(tsFilter?.predicate("/tmp/a.ts"), true);
	assert.equal(tsFilter?.predicate("/tmp/a.py"), false);
	assert.throws(() => resolveTypeFilter("unknown-type"), /Unknown grep type/);
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
