import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { GoalState } from "./format.js";
import { emitGoalEvent, persistGoal, type GoalRuntime } from "./state.js";
import {
  buildUpdateGoalCallText,
  buildUpdateGoalResultText,
  renderReusableText,
} from "./render.js";

const updateGoalSchema = {
  type: "object",
  properties: {
    status: {
      type: "string",
      enum: ["complete"],
      description:
        "Required. Set to complete only when the objective is achieved and no required work remains.",
    },
  },
  required: ["status"],
  additionalProperties: false,
} as const;

type UpdateGoalInput = {
  status?: unknown;
};

const getFirstText = (content: unknown): string => {
  if (!Array.isArray(content)) return "";
  const part = content.find(
    (item) =>
      item &&
      typeof item === "object" &&
      (item as { type?: unknown }).type === "text",
  );
  return typeof (part as { text?: unknown } | undefined)?.text === "string"
    ? (part as { text: string }).text
    : "";
};

export const registerGoalTools = (
  pi: ExtensionAPI,
  runtime: GoalRuntime,
): void => {
  pi.registerTool({
    name: "update_goal",
    label: "Update Goal",
    description:
      "Update the existing goal. Use this tool only to mark the goal achieved. Set status to `complete` only when the objective has actually been achieved and no required work remains. Do not mark a goal complete merely because you are stopping work. You cannot use this tool to pause or resume a goal; those status changes are controlled by the user.",
    promptSnippet:
      "Mark the current goal complete after a strict completion audit",
    promptGuidelines: [
      "Use update_goal only when the current pi-goal objective is fully achieved and verified against concrete evidence.",
      "Do not use update_goal to pause, resume, or abandon a goal.",
    ],
    parameters: updateGoalSchema,
    renderShell: "self",
    renderCall(_args, theme, context) {
      return renderReusableText(
        context.lastComponent,
        buildUpdateGoalCallText(runtime.goal, theme),
      );
    },
    renderResult(result, _options, theme, context) {
      const rawText = getFirstText((result as { content?: unknown }).content);
      return renderReusableText(
        context.lastComponent,
        buildUpdateGoalResultText(rawText, context.isError === true, theme),
      );
    },
    async execute(
      _toolCallId,
      input: UpdateGoalInput,
      _signal,
      _onUpdate,
      ctx,
    ) {
      if (input.status !== "complete") {
        return {
          content: [
            {
              type: "text",
              text: "update_goal can only mark the existing goal complete.",
            },
          ],
          isError: true,
        };
      }
      if (!runtime.goal) {
        return {
          content: [{ type: "text", text: "No goal is set." }],
          isError: true,
        };
      }
      const next: GoalState = {
        ...runtime.goal,
        status: "complete",
        updatedAt: Date.now(),
      };
      persistGoal(pi, runtime, ctx, next);
      emitGoalEvent(pi, "complete", next);
      return {
        content: [{ type: "text", text: "Goal marked complete." }],
        details: { goal: next },
      };
    },
  });
};

export const __test = { getFirstText };
