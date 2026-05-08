import { describe, expect, mock, test } from "bun:test";
import type { GoalState } from "./format.js";

mock.module("@mariozechner/pi-tui", () => ({
  Text: class {
    text = "";
    constructor(text = "") {
      this.text = text;
    }
    setText(value: string) {
      this.text = value;
    }
  },
  truncateToWidth: (value: string, width: number) => value.slice(0, width),
  visibleWidth: (value: string) => value.length,
}));

const { buildGoalEventText, buildUpdateGoalCallText, buildUpdateGoalResultText, previewObjective } = await import("./render.js");

const goal = (overrides: Partial<GoalState> = {}): GoalState => ({
  version: 1,
  id: "goal-1",
  objective: "patch the extension and validate gates",
  status: "active",
  timeUsedSeconds: 90,
  createdAt: 1,
  updatedAt: 2,
  ...overrides,
});

const plainTheme = {
  fg: (_token: string, text: string) => text,
  bold: (text: string) => text,
};

describe("goal rendering", () => {
  test("renders compact goal events like tool telemetry", () => {
    expect(buildGoalEventText({ details: { kind: "continuation", goal: goal() } }, {}, plainTheme)).toBe(
      "⚑ goal · continuing\n  ↳ patch the extension and validate gates"
    );
    expect(buildGoalEventText({ details: { kind: "paused", goal: goal({ status: "paused" }) } }, {}, plainTheme)).toBe(
      "‖ goal · paused · 1m\n  ↳ patch the extension and validate gates"
    );
    expect(buildGoalEventText({ details: { kind: "complete", goal: goal({ status: "complete" }) } }, {}, plainTheme)).toBe(
      "✓ goal · achieved · 1m\n  ↳ patch the extension and validate gates"
    );
  });

  test("does not render expand hints", () => {
    expect(buildGoalEventText({ details: { kind: "active", goal: goal() } }, {}, plainTheme)).not.toContain("ctrl+o");
  });

  test("omits elapsed usage for non-terminal historical events", () => {
    expect(buildGoalEventText({ details: { kind: "active", goal: goal() } }, {}, plainTheme)).toBe(
      "⚑ goal · active\n  ↳ patch the extension and validate gates"
    );
    expect(buildGoalEventText({ details: { kind: "continuation", goal: goal() } }, {}, plainTheme)).not.toContain("1m");
    expect(buildGoalEventText({ details: { kind: "resumed", goal: goal() } }, {}, plainTheme)).toContain("1m");
  });

  test("truncates objective previews", () => {
    expect(previewObjective("one   two\nthree", 20)).toBe("one two three");
    expect(previewObjective("x".repeat(25), 10)).toBe("xxxxxxxxx…");
  });

  test("renders update_goal as compact two-line tool telemetry", () => {
    expect(buildUpdateGoalCallText(goal(), plainTheme)).toBe("✓ goal · complete\n  ↳ patch the extension and validate gates");
    expect(buildUpdateGoalResultText("Goal marked complete.", false, plainTheme)).toBe("");
    expect(buildUpdateGoalResultText("No goal is set.", true, plainTheme)).toBe("  No goal is set.");
  });
});
