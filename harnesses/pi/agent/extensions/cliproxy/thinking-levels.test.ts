import { expect, test } from "bun:test";
import { piThinkingLevelMap } from "./thinking-levels.ts";

test("projects fetched efforts onto Pi thinking levels", () => {
  expect(piThinkingLevelMap(["low", "high", "max", "ultra"])).toEqual({
    off: null,
    minimal: null,
    low: "low",
    medium: null,
    high: "high",
    xhigh: null,
    max: "ultra",
  });
});
