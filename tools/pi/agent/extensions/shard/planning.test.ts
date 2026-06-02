import { describe, expect, test } from "bun:test";
import {
  buildTaskPlan,
  normalizeChildMode,
  normalizeTasks,
  selectRuntimeTools,
  validateMaxToolCalls,
  validateMaxTurns,
  validateTimeoutSec,
} from "./planning.js";

const unwrap = <T>(
  result: { ok: true; value: T } | { ok: false; error: string },
): T => {
  if (!result.ok) throw new Error(result.error);
  return result.value;
};

describe("shard task planning", () => {
  test("one task + omitted mode derives worker", () => {
    const plan = unwrap(buildTaskPlan({ tasks: ["inspect"] }, "/repo"));
    expect(plan.childMode).toBe("worker");
    expect(plan.mode).toBe("single");
    expect(plan.tasks[0]?.childMode).toBe("worker");
  });

  test("multiple tasks + omitted mode derives explorer", () => {
    const plan = unwrap(buildTaskPlan({ tasks: ["a", "b"] }, "/repo"));
    expect(plan.childMode).toBe("explorer");
    expect(plan.mode).toBe("parallel");
    expect(plan.tasks.map((task) => task.childMode)).toEqual([
      "explorer",
      "explorer",
    ]);
  });

  test("explicit explorer with one task is valid", () => {
    const plan = unwrap(
      buildTaskPlan({ mode: "explorer", tasks: ["inspect"] }, "/repo"),
    );
    expect(plan.childMode).toBe("explorer");
    expect(plan.mode).toBe("single");
  });

  test("explicit explorer with multiple tasks is valid", () => {
    const plan = unwrap(
      buildTaskPlan({ mode: "explorer", tasks: ["a", "b"] }, "/repo"),
    );
    expect(plan.childMode).toBe("explorer");
    expect(plan.tasks).toHaveLength(2);
  });

  test("explicit worker with one task is valid", () => {
    const plan = unwrap(
      buildTaskPlan({ mode: "worker", tasks: ["fix"] }, "/repo"),
    );
    expect(plan.childMode).toBe("worker");
    expect(plan.tasks).toHaveLength(1);
  });

  test("explicit worker with multiple tasks is rejected", () => {
    const plan = buildTaskPlan(
      { mode: "worker", tasks: ["fix a", "fix b"] },
      "/repo",
    );
    expect(plan.ok).toBe(false);
    if (!plan.ok)
      expect(plan.error).toContain("worker mode accepts exactly one task");
  });

  test("tasks are trimmed", () => {
    expect(unwrap(normalizeTasks(["  a  ", "\tb\n"]))).toEqual(["a", "b"]);
  });

  test("empty task is rejected", () => {
    const result = normalizeTasks(["ok", "   "]);
    expect(result.ok).toBe(false);
    if (!result.ok)
      expect(result.error).toBe("tasks[1] must be a non-empty string.");
  });

  test("too many tasks rejected", () => {
    const result = normalizeTasks(
      Array.from({ length: 9 }, (_, index) => `task ${index}`),
    );
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("shard accepts up to 8 tasks.");
  });

  test("invalid mode rejected", () => {
    const result = normalizeChildMode("reviewer", 1);
    expect(result.ok).toBe(false);
    if (!result.ok)
      expect(result.error).toBe(
        'Invalid mode "reviewer". Expected "worker" or "explorer".',
      );
  });
});

describe("shard runtime tool selection", () => {
  test("explorer tool filter returns only active read grep find", () => {
    expect(
      selectRuntimeTools("explorer", [
        "bash",
        "read",
        "edit",
        "grep",
        "find",
        "write",
      ]),
    ).toEqual(["read", "grep", "find"]);
  });

  test("explorer tool filter preserves active-tool order", () => {
    expect(selectRuntimeTools("explorer", ["find", "read", "grep"])).toEqual([
      "find",
      "read",
      "grep",
    ]);
  });

  test("worker tool filter returns all active tools", () => {
    const tools = ["read", "edit", "write", "bash"];
    expect(selectRuntimeTools("worker", tools)).toBe(tools);
  });
});

describe("shard timeout validation", () => {
  test("timeout omitted returns undefined", () => {
    expect(unwrap(validateTimeoutSec(undefined))).toBeUndefined();
  });

  test("valid timeout is accepted", () => {
    expect(unwrap(validateTimeoutSec(1.5))).toBe(1.5);
  });

  test("invalid timeout rejected", () => {
    const result = validateTimeoutSec(0);
    expect(result.ok).toBe(false);
    if (!result.ok)
      expect(result.error).toBe(
        "timeoutSec must be a positive finite number of seconds.",
      );
  });

  test("timeout over 86400 rejected", () => {
    const result = validateTimeoutSec(86401);
    expect(result.ok).toBe(false);
    if (!result.ok)
      expect(result.error).toBe("timeoutSec must be <= 86400 seconds.");
  });
});

describe("shard budget validation", () => {
  test("budgets omitted return undefined", () => {
    expect(unwrap(validateMaxTurns(undefined))).toBeUndefined();
    expect(unwrap(validateMaxToolCalls(undefined))).toBeUndefined();
  });

  test("valid budgets are accepted and copied into task plan", () => {
    const plan = unwrap(
      buildTaskPlan({ tasks: ["tiny"], maxTurns: 2, maxToolCalls: 5 }, "/repo"),
    );
    expect(plan.tasks[0]?.maxTurns).toBe(2);
    expect(plan.tasks[0]?.maxToolCalls).toBe(5);
  });

  test("invalid budgets are rejected", () => {
    const turns = validateMaxTurns(1.5);
    const calls = validateMaxToolCalls(0);
    expect(turns.ok).toBe(false);
    expect(calls.ok).toBe(false);
    if (!turns.ok)
      expect(turns.error).toBe("maxTurns must be a positive integer.");
    if (!calls.ok)
      expect(calls.error).toBe("maxToolCalls must be a positive integer.");
  });

  test("excessive budgets are rejected", () => {
    const turns = validateMaxTurns(101);
    const calls = validateMaxToolCalls(1001);
    expect(turns.ok).toBe(false);
    expect(calls.ok).toBe(false);
    if (!turns.ok) expect(turns.error).toBe("maxTurns must be <= 100.");
    if (!calls.ok) expect(calls.error).toBe("maxToolCalls must be <= 1000.");
  });
});
