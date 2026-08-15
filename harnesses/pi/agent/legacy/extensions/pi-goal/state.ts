import type {
  ExtensionAPI,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import type { GoalEventKind, GoalState } from "./format.js";
import { goalContentForLLM } from "./prompts.js";

export const CUSTOM_TYPE = "pi-goal";
export const EVENT_TYPE = "pi-goal-event";

export type GoalRuntime = {
  goal: GoalState | null;
  activeTurnStartedAt: number | null;
  continuationQueued: boolean;
};

type GoalEntryData = {
  goal?: GoalState | null;
};

type BranchSessionManager = ExtensionContext["sessionManager"] & {
  getBranch?: () => unknown[];
};

export const createGoalRuntime = (): GoalRuntime => ({
  goal: null,
  activeTurnStartedAt: null,
  continuationQueued: false,
});

const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object";

const getEntryData = (entry: unknown): GoalEntryData | undefined => {
  if (!isRecord(entry)) return undefined;
  if (entry["type"] !== "custom" || entry["customType"] !== CUSTOM_TYPE)
    return undefined;
  return isRecord(entry["data"]) ? (entry["data"] as GoalEntryData) : undefined;
};

export const latestStateFromSession = (
  ctx: ExtensionContext,
): { goal: GoalState | null } => {
  const sessionManager = ctx.sessionManager as BranchSessionManager;
  const entries = sessionManager.getBranch?.() ?? sessionManager.getEntries();
  for (let index = entries.length - 1; index >= 0; index--) {
    const data = getEntryData(entries[index]);
    if (data) {
      return { goal: data.goal ?? null };
    }
  }
  return { goal: null };
};

const goalToolNames = ["update_goal"] as const;

export const syncGoalTools = (pi: ExtensionAPI, runtime: GoalRuntime): void => {
  const active = new Set(pi.getActiveTools());
  for (const name of goalToolNames) active.delete(name);
  if (runtime.goal?.status === "active") active.add("update_goal");
  pi.setActiveTools(Array.from(active));
};

export const persistGoal = (
  pi: ExtensionAPI,
  runtime: GoalRuntime,
  _ctx: ExtensionContext,
  next: GoalState | null,
): void => {
  runtime.goal = next;
  pi.appendEntry(CUSTOM_TYPE, { goal: next });
  syncGoalTools(pi, runtime);
};

export const emitGoalEvent = (
  pi: ExtensionAPI,
  kind: GoalEventKind,
  state: GoalState,
  options?: {
    triggerTurn?: boolean;
    deliverAs?: "steer" | "followUp" | "nextTurn";
  },
): void => {
  pi.sendMessage(
    {
      customType: EVENT_TYPE,
      content: goalContentForLLM(kind, state),
      display: true,
      details: { kind, goal: state, timestamp: Date.now() },
    },
    options,
  );
};

export const queueContinuation = (
  pi: ExtensionAPI,
  runtime: GoalRuntime,
  state: GoalState,
): void => {
  if (runtime.continuationQueued || state.status !== "active") return;
  runtime.continuationQueued = true;
  void Promise.resolve().then(() => {
    runtime.continuationQueued = false;
    if (
      !runtime.goal ||
      runtime.goal.id !== state.id ||
      runtime.goal.status !== "active"
    )
      return;
    emitGoalEvent(pi, "continuation", runtime.goal, {
      triggerTurn: true,
      deliverAs: "followUp",
    });
  });
};

export const accountTurnEnd = (
  pi: ExtensionAPI,
  runtime: GoalRuntime,
  ctx: ExtensionContext,
  now = Date.now(),
): GoalState | null => {
  if (!runtime.goal || runtime.goal.status !== "active") return null;
  const elapsed = runtime.activeTurnStartedAt
    ? Math.max(0, Math.round((now - runtime.activeTurnStartedAt) / 1000))
    : 0;
  runtime.activeTurnStartedAt = null;
  const next: GoalState = {
    ...runtime.goal,
    timeUsedSeconds: runtime.goal.timeUsedSeconds + elapsed,
    updatedAt: now,
  };
  persistGoal(pi, runtime, ctx, next);
  return next;
};
