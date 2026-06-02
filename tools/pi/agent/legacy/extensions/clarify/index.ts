import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { ClarifyParamsSchema, type ClarifyResult } from "./models.js";
import {
  buildSuccessText,
  normalizeQuestions,
  sortAnswers,
  validateQuestions,
} from "./results.js";
import {
  createClarifyComponent,
  renderCallText,
  renderResultText,
} from "./ui.js";

const DESCRIPTION = "Collect user decisions in interactive sessions.";

const PROMPT_GUIDELINES = [
  "Blocked on user decision: call clarify.",
  "Use details.answers as source of truth.",
];

export default function clarifyExtension(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "clarify",
    label: "Clarify",
    description: DESCRIPTION,
    promptSnippet: "Collect 1-3 user-decision answers",
    promptGuidelines: PROMPT_GUIDELINES,
    parameters: ClarifyParamsSchema,
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      if (!ctx.hasUI) {
        throw new Error("clarify requires interactive terminal UI.");
      }

      const questions = normalizeQuestions(params.questions);
      const validationError = validateQuestions(questions);
      if (validationError) {
        throw new Error(validationError);
      }

      ctx.ui.notify("Clarify waiting for user input", "info");

      const result = await ctx.ui.custom<ClarifyResult>(
        (tui, theme, _kb, done) =>
          createClarifyComponent(questions, tui, theme, done),
      );

      if (!result) {
        throw new Error("clarify requires interactive terminal UI.");
      }

      if (result.cancelled) {
        throw new Error(result.reason ?? "User cancelled clarification");
      }

      const answers = sortAnswers(result.answers, questions);
      return {
        content: [{ type: "text", text: buildSuccessText(answers) }],
        details: { ...result, answers },
      };
    },
    renderCall(_args, theme) {
      return new Text(theme.fg("muted", renderCallText()), 0, 0);
    },
    renderResult(result, _options, theme) {
      const details = result.details as ClarifyResult | undefined;
      const text = details
        ? renderResultText(details)
        : result.content[0]?.type === "text"
          ? result.content[0].text
          : "";
      const color = details?.cancelled ? "warning" : "success";
      return new Text(theme.fg(color, text), 0, 0);
    },
  });
}
