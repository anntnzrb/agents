import { describe, expect, test } from "bun:test";
import {
  entriesBetweenAncestorAndLeaf,
  isAncestor,
  makeActionItems,
} from "./tree-utils.js";

function entry(id: string, parentId: string | null, role = "user") {
  return {
    id,
    parentId,
    type: "message",
    message: { role, content: `${role} ${id}` },
  };
}

const entries = [
  entry("a", null),
  entry("b", "a", "assistant"),
  entry("c", "b", "toolResult"),
  entry("d", "c"),
];

const sm = {
  getEntry(id: string) {
    return entries.find((e) => e.id === id);
  },
  getBranch(leafId: string) {
    const out = [];
    let current = this.getEntry(leafId);
    while (current) {
      out.unshift(current);
      current = current.parentId ? this.getEntry(current.parentId) : undefined;
    }
    return out;
  },
};

describe("treex tree utils", () => {
  test("detects ancestors", () => {
    expect(isAncestor(sm as never, "a", "d")).toBe(true);
    expect(isAncestor(sm as never, "c", "b")).toBe(false);
  });

  test("returns ancestor-to-leaf segment", () => {
    expect(entriesBetweenAncestorAndLeaf(sm as never, "b", "d").map((e) => e.id)).toEqual(["b", "c", "d"]);
  });

  test("groups assistant and tool result rows into one assistant turn", () => {
    const items = makeActionItems(entries as never);
    expect(items.map((i) => i.groupId)).toEqual([
      "turn-1-user",
      "turn-1-assistant",
      "turn-1-assistant",
      "turn-2-user",
    ]);
    expect(items.every((i) => i.action === "summarize")).toBe(true);
  });
});
