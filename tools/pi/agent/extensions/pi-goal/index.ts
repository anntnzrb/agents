import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { handleGoalCommand, makeGoalArgumentCompletions } from "./command.js";
import { registerGoalFooterContribution } from "./footer.js";
import { truncateObjective } from "./format.js";
import { registerGoalRenderer, type MessageRendererApi } from "./render.js";
import {
  accountTurnEnd,
  createGoalRuntime,
  latestStateFromSession,
  persistGoal,
  queueContinuation,
  syncGoalTools,
} from "./state.js";
import { registerGoalTools } from "./tools.js";

export default function piGoalExtension(pi: ExtensionAPI): void {
  const runtime = createGoalRuntime();

  registerGoalFooterContribution();
  registerGoalRenderer(pi as unknown as MessageRendererApi);
  registerGoalTools(pi, runtime);

  pi.registerCommand("goal", {
    description:
      "Set, view, pause, resume, clear, or configure a long-running goal",
    getArgumentCompletions: makeGoalArgumentCompletions(runtime),
    handler: (args: string, ctx: Parameters<typeof handleGoalCommand>[3]) =>
      handleGoalCommand(pi, runtime, args, ctx),
  });

  pi.on("session_start", (event, ctx) => {
    const restored = latestStateFromSession(ctx);
    runtime.goal = restored.goal;
    runtime.continuationQueued = false;
    runtime.activeTurnStartedAt = null;
    syncGoalTools(pi, runtime);

    if (runtime.goal?.status === "active" && event.reason === "reload") {
      const paused = {
        ...runtime.goal,
        status: "paused" as const,
        updatedAt: Date.now(),
      };
      persistGoal(pi, runtime, ctx, paused);
      ctx.ui.notify(
        `‖ Goal paused after reload: ${truncateObjective(paused.objective)}\nUse /goal resume to continue, or /goal clear to stop.`,
        "info",
      );
      return;
    }

    if (runtime.goal?.status === "active") {
      ctx.ui.notify(
        `⚑ Goal restored: ${truncateObjective(runtime.goal.objective)}\nUse /goal pause to stop continuation, or /goal clear to remove it.`,
        "info",
      );
    }
  });

  pi.on("turn_start", () => {
    runtime.activeTurnStartedAt = Date.now();
  });

  pi.on("turn_end", (_event, ctx) => {
    accountTurnEnd(pi, runtime, ctx);
  });

  pi.on("agent_end", (_event, ctx) => {
    const hasPendingMessages = (
      ctx as typeof ctx & { hasPendingMessages?: () => boolean }
    ).hasPendingMessages;
    if (
      !runtime.goal ||
      runtime.goal.status !== "active" ||
      hasPendingMessages?.()
    )
      return;
    queueContinuation(pi, runtime, runtime.goal);
  });
}
