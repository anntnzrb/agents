import assert from "node:assert/strict";
import test from "node:test";

import { buildFdArgs, normalizeLimit, normalizeSearchRoots, normalizeTimeout } from "./logic.js";

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

test("normalizeLimit enforces positive values with cap", () => {
	assert.equal(normalizeLimit(undefined), 1000);
	assert.equal(normalizeLimit(999999), 10000);
	assert.throws(() => normalizeLimit(0), /positive number/);
});

test("normalizeTimeout validates positive values", () => {
	assert.equal(normalizeTimeout(undefined), 5000);
	assert.throws(() => normalizeTimeout(-10), /positive number/);
});

test("buildFdArgs toggles hidden and handles full-path patterns", () => {
	const hiddenArgs = buildFdArgs("*.ts", "/repo", true, 5);
	assert.ok(hiddenArgs.includes("--hidden"));
	assert.ok(hiddenArgs.includes("--max-results"));

	const scopedArgs = buildFdArgs("src/**/*.ts", "/repo", false, 5);
	assert.ok(scopedArgs.includes("--full-path"));
	assert.ok(scopedArgs.includes("**/src/**/*.ts"));
	assert.equal(scopedArgs.includes("--hidden"), false);
});
