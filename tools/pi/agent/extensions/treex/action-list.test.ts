import { describe, expect, test } from "bun:test";
import {
  actionLetter,
  filterActionableEntries,
  makeActionItems,
  setGroupAction,
  type SessionEntry,
} from "./tree-utils.js";

function message(id: string, role: string, content = role): SessionEntry {
  return { id, type: "message", message: { role, content } };
}

describe("treex action helpers", () => {
  test("maps actions to P/S/D letters", () => {
    expect(actionLetter("pick")).toBe("P");
    expect(actionLetter("summarize")).toBe("S");
    expect(actionLetter("drop")).toBe("D");
  });

  test("filters out non-actionable metadata entries", () => {
    const entries: SessionEntry[] = [
      message("u1", "user"),
      { id: "m1", type: "model_change", modelId: "foo" },
      { id: "t1", type: "thinking_level_change", thinkingLevel: "high" },
      { id: "s1", type: "branch_summary", summary: "summary" },
    ];

    expect(filterActionableEntries(entries).map((entry) => entry.id)).toEqual(["u1", "s1"]);
  });

  test("updates all items in a group and keeps summarize default", () => {
    const entries = [
      message("u1", "user"),
      message("a1", "assistant"),
      message("a2", "toolResult"),
    ];
    const items = makeActionItems(entries);

    expect(items.every((item) => item.action === "summarize")).toBe(true);

    const updated = setGroupAction(items, "turn-1-assistant", "pick");
    expect(updated.map((item) => item.action)).toEqual(["summarize", "pick", "pick"]);
  });
});
