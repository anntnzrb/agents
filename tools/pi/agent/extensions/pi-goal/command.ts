import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";

type GoalCommandContext = ExtensionCommandContext & {
  isIdle: () => boolean;
  ui: ExtensionCommandContext["ui"] & {
    confirm: (title: string, message: string) => Promise<boolean>;
  };
};
type GoalMessageApi = ExtensionAPI & {
  sendUserMessage: (content: string, options?: { deliverAs?: "steer" | "followUp" }) => Promise<void> | void;
};

import { goalStatusLabel, goalUsageSummary, MAX_GOAL_OBJECTIVE_CHARS, statusLine, truncateObjective, type GoalState, type GoalStatus } from "./format.js";
import { emitGoalEvent, persistGoal, queueContinuation, type GoalRuntime } from "./state.js";

const validateObjective = (objective: string): string | undefined => {
  if (objective.length === 0) return "Usage: /goal <objective>";
  const chars = [...objective].length;
  if (chars > MAX_GOAL_OBJECTIVE_CHARS) {
    return `Goal objective is too long: ${chars} characters. Limit: ${MAX_GOAL_OBJECTIVE_CHARS} characters. Put longer instructions in a file and refer to that file in the goal, for example: /goal follow the instructions in docs/goal.md.`;
  }
  return undefined;
};

const goalSuggestionCommandRules = `Return exactly one command and nothing else: no markdown fence, no explanation, no bullets.

The command must:
- Start with /goal.
- Express concrete deliverables, validation/evidence criteria, and a stop condition.
- Adapt evidence to the actual domain: code, data cleanup, research, finance, browser/API work, shopping, writing, or whatever the task describes.
- Mention files, repos, systems, sources, commands, or constraints only when they are explicitly known from the task input.
- Avoid hardcoded Pi-extension gates like ephemeral Pi validation, sync runtime files, typecheck, lint, or tests unless the task is actually about Pi extensions or software that uses those gates.
- Avoid vague objectives like "improve this" or "continue working".
- Do not set, pause, resume, clear, or update a goal. Only draft the command for the user to copy-paste.`;

export const buildGoalSuggestionPrompt = (intent: string): string => `Draft one copy-pasteable Pi /goal command from this user intent.

<user_intent>
${intent.trim()}
</user_intent>

Use only the intent above as the authoritative task input. Do not infer missing requirements from the current conversation, session history, repository, or environment.
${goalSuggestionCommandRules}`;

export const buildContextGoalSuggestionPrompt = (): string => `Draft one copy-pasteable Pi /goal command for the user's current work.

Infer the objective from the recent conversation/session context. Prefer the most recent concrete task. Avoid stale context and do not invent requirements; if the objective is unclear, return a /goal command asking for clarification as the deliverable.
${goalSuggestionCommandRules}`;

const createGoal = (objective: string, now = Date.now()): GoalState => ({
  version: 1,
  id: `${now}-${Math.random().toString(16).slice(2)}`,
  objective,
  status: "active",
  timeUsedSeconds: 0,
  createdAt: now,
  updatedAt: now,
});

export const handleGoalCommand = async (
  pi: ExtensionAPI,
  runtime: GoalRuntime,
  args: string,
  ctx: ExtensionCommandContext
): Promise<void> => {
  const goalCtx = ctx as GoalCommandContext;
  const trimmed = args.trim();
  const now = Date.now();

  if (trimmed.length === 0 || trimmed === "status") {
    if (!runtime.goal) {
      ctx.ui.notify("Usage: /goal <objective>", "info");
      return;
    }
    ctx.ui.notify(
      `Goal ${goalStatusLabel(runtime.goal.status)}\n${goalUsageSummary(runtime.goal)}\n${statusLine(runtime.goal) ?? ""}`,
      "info"
    );
    return;
  }

  if (trimmed === "suggest" || trimmed.startsWith("suggest ")) {
    const intent = trimmed.slice("suggest".length).trim();
    const prompt = intent.length === 0 ? buildContextGoalSuggestionPrompt() : buildGoalSuggestionPrompt(intent);
    await (pi as GoalMessageApi).sendUserMessage(prompt);
    return;
  }

  if (trimmed === "statusbar" || trimmed.startsWith("statusbar ")) {
    ctx.ui.notify("Goal status now lives in the custom footer and is always enabled when goal state exists.", "info");
    return;
  }

  if (trimmed === "clear") {
    if (!runtime.goal) {
      ctx.ui.notify("No goal is set.", "info");
      return;
    }
    const previous = runtime.goal;
    persistGoal(pi, runtime, ctx, null);
    emitGoalEvent(pi, "cleared", previous);
    return;
  }

  if (trimmed === "pause" || trimmed === "resume") {
    if (!runtime.goal) {
      ctx.ui.notify("No goal is set.", "warning");
      return;
    }
    const status: GoalStatus = trimmed === "pause" ? "paused" : "active";
    const next: GoalState = { ...runtime.goal, status, updatedAt: now };
    persistGoal(pi, runtime, ctx, next);
    emitGoalEvent(pi, status === "active" ? "resumed" : "paused", next);
    if (status === "active" && goalCtx.isIdle()) queueContinuation(pi, runtime, next);
    return;
  }

  const validationError = validateObjective(trimmed);
  if (validationError) {
    ctx.ui.notify(validationError, "warning");
    return;
  }
  if (runtime.goal && runtime.goal.status !== "complete") {
    const ok = await goalCtx.ui.confirm("Replace goal?", `Current: ${truncateObjective(runtime.goal.objective)}\n\nNew: ${truncateObjective(trimmed)}`);
    if (!ok) return;
  }
  const next = createGoal(trimmed, now);
  persistGoal(pi, runtime, ctx, next);
  emitGoalEvent(pi, "active", next, { triggerTurn: goalCtx.isIdle() });
};

export const makeGoalArgumentCompletions = (runtime: GoalRuntime) => (prefix: string): Array<{ value: string; label: string }> | null => {
  const values = ["status", "suggest"];
  if (runtime.goal) values.push("clear");
  if (runtime.goal?.status === "active") values.push("pause");
  if (runtime.goal?.status === "paused") values.push("resume");
  const filtered = values.filter((value) => value.startsWith(prefix));
  return filtered.length === 0 ? null : filtered.map((value) => ({ value, label: value }));
};

export const __test = { buildContextGoalSuggestionPrompt, buildGoalSuggestionPrompt };
