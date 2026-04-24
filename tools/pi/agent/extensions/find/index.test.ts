import assert from "node:assert/strict";
import test from "node:test";

import { buildFdArgs, normalizeKind, normalizeLimit, normalizeSearchRoots, normalizeTimeout } from "./logic.js";

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

test("normalizeKind defaults to files and validates supported values", () => {
	assert.equal(normalizeKind(undefined), "file");
	assert.equal(normalizeKind(""), "file");
	assert.equal(normalizeKind("file"), "file");
	assert.equal(normalizeKind("directory"), "directory");
	assert.equal(normalizeKind("any"), "any");
	assert.throws(() => normalizeKind("symlink"), /kind must be one of/);
});

test("buildFdArgs toggles hidden and handles full-path patterns", () => {
	const hiddenArgs = buildFdArgs("*.ts", "/repo", true, 5, "file", true);
	assert.ok(hiddenArgs.includes("--hidden"));
	assert.ok(hiddenArgs.includes("--max-results"));

	const scopedArgs = buildFdArgs("src/**/*.ts", "/repo", false, 5, "file", true);
	assert.ok(scopedArgs.includes("--full-path"));
	assert.ok(scopedArgs.includes("**/src/**/*.ts"));
	assert.equal(scopedArgs.includes("--hidden"), false);
});

test("buildFdArgs applies kind and ignore controls", () => {
	const fileArgs = buildFdArgs("*.ts", "/repo", true, 5, "file", true);
	assert.deepEqual(fileArgs.slice(fileArgs.indexOf("--type"), fileArgs.indexOf("--type") + 2), ["--type", "file"]);
	assert.equal(fileArgs.includes("--no-ignore"), false);

	const directoryArgs = buildFdArgs("src*", "/repo", true, 5, "directory", false);
	assert.deepEqual(directoryArgs.slice(directoryArgs.indexOf("--type"), directoryArgs.indexOf("--type") + 2), ["--type", "directory"]);
	assert.ok(directoryArgs.includes("--no-ignore"));

	const anyArgs = buildFdArgs("*", "/repo", true, 5, "any", true);
	assert.equal(anyArgs.includes("--type"), false);
});
