import { expect, test } from "bun:test";

import { normalizeSearchRoots } from "./search-input.js";

test("normalizeSearchRoots supports multipath trimming and dedupe", () => {
  const roots = normalizeSearchRoots([
    "apps",
    "packages",
    "packages",
    " libs ",
  ]);
  expect(roots).toEqual(["apps", "packages", "libs"]);
});

test("normalizeSearchRoots defaults omitted, empty, and blank roots to current directory", () => {
  expect(normalizeSearchRoots(undefined)).toEqual(["."]);
  expect(normalizeSearchRoots([])).toEqual(["."]);
  expect(normalizeSearchRoots([" ", "\t"])).toEqual(["."]);
});

test("normalizeSearchRoots keeps commas literal", () => {
  const roots = normalizeSearchRoots(["apps,packages"]);
  expect(roots).toEqual(["apps,packages"]);
});
