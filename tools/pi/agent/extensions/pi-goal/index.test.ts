import { describe, expect, test } from "bun:test";
import { __test as commandTest, handleGoalCommand, makeGoalArgumentCompletions } from "./command.js";
import { formatElapsed, type GoalState, goalUsage, statusLine } from "./format.js";
import { continuationPrompt, goalContentForLLM } from "./prompts.js";
import { accountTurnEnd, createGoalRuntime, latestStateFromSession, syncGoalTools } from "./state.js";

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

describe("goal formatting", () => {
  test("formats elapsed time", () => {
    expect(formatElapsed(59)).toBe("59s");
    expect(formatElapsed(60)).toBe("1m");
    expect(formatElapsed(90 * 60)).toBe("1h 30m");
    expect(formatElapsed(24 * 60 * 60)).toBe("1d 0h 0m");
  });

  test("formats status and usage", () => {
    expect(goalUsage(goal())).toBe("1m");
    expect(statusLine(goal())).toBe("Pursuing goal (1m)");
    expect(statusLine(goal({ status: "complete" }))).toBe("Goal achieved (1m)");
  });
});

describe("/goal parser", () => {
  const completionValues = (runtimeGoal: GoalState | null, prefix = "") => {
    const runtime = createGoalRuntime();
    runtime.goal = runtimeGoal;
    return makeGoalArgumentCompletions(runtime)(prefix)?.map((item) => item.value) ?? [];
  };

  test("exposes dynamic lifecycle completions by goal state", () => {
    expect(completionValues(null).toSorted()).toEqual(["status", "suggest"]);
    expect(completionValues(goal()).toSorted()).toEqual(["clear", "pause", "status", "suggest"]);
    expect(completionValues(goal({ status: "paused" })).toSorted()).toEqual(["clear", "resume", "status", "suggest"]);
    expect(completionValues(goal({ status: "complete" })).toSorted()).toEqual(["clear", "status", "suggest"]);
  });

  test("filters dynamic completions by prefix", () => {
    expect(completionValues(goal(), "p")).toEqual(["pause"]);
    expect(completionValues(goal({ status: "paused" }), "r")).toEqual(["resume"]);
    expect(completionValues(goal(), "r")).toEqual([]);
    expect(JSON.stringify(completionValues(goal(), "statusbar"))).not.toContain("statusbar");
  });

  test("builds an argument-driven meta-goal suggestion prompt", () => {
    const prompt = commandTest.buildGoalSuggestionPrompt("clean six Excel sheets");
    expect(prompt).toContain("Draft one copy-pasteable Pi /goal command from this user intent");
    expect(prompt).toContain("<user_intent>\nclean six Excel sheets\n</user_intent>");
    expect(prompt).toContain("Use only the intent above as the authoritative task input");
    expect(prompt).toContain("Do not infer missing requirements from the current conversation");
    expect(prompt).toContain("Return exactly one command and nothing else");
    expect(prompt).toContain("Adapt evidence to the actual domain");
    expect(prompt).toContain("Avoid hardcoded Pi-extension gates");
    expect(prompt).not.toContain("--tokens");
    expect(prompt).not.toContain("current work");
  });

  test("builds a blank suggest prompt from recent context", () => {
    const prompt = commandTest.buildContextGoalSuggestionPrompt();
    expect(prompt).toContain("Draft one copy-pasteable Pi /goal command for the user's current work");
    expect(prompt).toContain("Infer the objective from the recent conversation/session context");
    expect(prompt).toContain("Avoid stale context");
    expect(prompt).toContain("Return exactly one command and nothing else");
    expect(prompt).not.toContain("<user_intent>");
  });

  test("suggest command sends context prompt when blank and intent prompt when provided", async () => {
    const sent: string[] = [];
    const pi = { sendUserMessage: (content: string) => sent.push(content) };
    const ctx = { ui: { notify: () => undefined } };
    const runtime = createGoalRuntime();

    await handleGoalCommand(pi as never, runtime, "suggest", ctx as never);
    await handleGoalCommand(pi as never, runtime, "suggest clean six Excel sheets", ctx as never);

    expect(sent).toHaveLength(2);
    expect(sent[0]).toContain("Infer the objective from the recent conversation/session context");
    expect(sent[1]).toContain("<user_intent>\nclean six Excel sheets\n</user_intent>");
    expect(sent[1]).toContain("Do not infer missing requirements from the current conversation");
  });
});


describe("goal prompts", () => {
  test("continuation prompt keeps Codex-native audit language", () => {
    const prompt = continuationPrompt(goal());
    expect(prompt).toContain("Continue working toward the active thread goal.");
    expect(prompt).toContain("<untrusted_objective>");
    expect(prompt).toContain("Build a prompt-to-artifact checklist");
    expect(prompt).toContain("call update_goal with status \"complete\"");
  });

  test("llm-visible custom messages are actionable", () => {
    expect(goalContentForLLM("continuation", goal())).toContain("Choose the next concrete action");
    expect(goalContentForLLM("paused", goal())).toContain("Stop pursuing it for now");
  });
});

describe("goal lifecycle helpers", () => {
  test("restores the latest branch goal state", () => {
    const first = goal({ id: "first", objective: "old" });
    const second = goal({ id: "second", objective: "new", status: "paused" });
    const ctx = {
      sessionManager: {
        getEntries: () => [],
        getBranch: () => [
          { type: "custom", customType: "pi-goal", data: { goal: first } },
          { type: "custom", customType: "pi-goal", data: { goal: second } },
        ],
      },
    };

    expect(latestStateFromSession(ctx as never)).toEqual({ goal: second });
  });

  test("syncs tools by lifecycle state", () => {
    const activeTools = ["read"];
    const pi = {
      getActiveTools: () => activeTools,
      setActiveTools: (tools: string[]) => {
        activeTools.splice(0, activeTools.length, ...tools);
      },
    };
    const runtime = createGoalRuntime();

    syncGoalTools(pi as never, runtime);
    expect(activeTools.toSorted()).toEqual(["read"]);

    runtime.goal = goal();
    syncGoalTools(pi as never, runtime);
    expect(activeTools.toSorted()).toEqual(["read", "update_goal"]);

    runtime.goal = goal({ status: "paused" });
    syncGoalTools(pi as never, runtime);
    expect(activeTools).toEqual(["read"]);
  });

  test("accounts elapsed turn time without token limits", () => {
    const runtime = createGoalRuntime();
    runtime.goal = goal({ timeUsedSeconds: 1 });
    runtime.activeTurnStartedAt = 1_000;
    const persisted: unknown[] = [];
    const pi = {
      appendEntry: (_customType: string, data: unknown) => persisted.push(data),
      getActiveTools: () => ["update_goal"],
      setActiveTools: (_tools: string[]) => undefined,
    };
    const ctx = {};

    const next = accountTurnEnd(pi as never, runtime, ctx as never, 3_000);

    expect(next?.status).toBe("active");
    expect(next?.timeUsedSeconds).toBe(3);
    expect(persisted).toHaveLength(1);
  });
});
