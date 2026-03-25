import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";
import { ClarifyParamsSchema, type ClarifyResult } from "./models.js";
import { buildSuccessText, normalizeQuestions, sortAnswers, validateQuestions } from "./results.js";
import { createClarifyComponent, renderCallText, renderResultText } from "./ui.js";

const DESCRIPTION = [
  "Interactive user-decision collection: requirements, preferences, approvals, constraints.",
  "Use proactively when progress blocks on something only user can decide, confirm, or prioritize.",
  "Strong signals: ambiguous implementation direction, competing tradeoffs, missing requirement, approval gate, naming/style preference, fork needing user intent.",
  "Prefer clarify over plain-prose questioning when direct user input needed before proceeding.",
  "Default: 1 focused question. Use 2-3 only when all answers required before continuing.",
  "Prefer explicit options when likely choices known; keep custom input unless choice truly closed.",
  "Options may mark one choice as recommended/default, and questions may set timeoutSeconds for auto-select fallback.",
  "Do not use for facts discoverable from repo, logs, docs, tools.",
  "Interactive sessions only; non-interactive fails cleanly, no guessing.",
].join(" ");

const PROMPT_GUIDELINES = [
  "Blocked on user intent, preference, requirement, approval, prioritization: call clarify; do not guess; avoid normal assistant-prose questioning.",
  "Default user-decision path mid-task: clarify.",
  "Keep short: 1 question if possible, max 3.",
  "Each question: one decision, concrete, immediately answerable.",
  "If likely choices known, provide 2-5 focused options, short descriptions; leave allowOther enabled unless choice truly closed.",
  "When one choice is the safest default, mark that option as recommended instead of explaining it in prose.",
  "Use timeoutSeconds only when auto-selecting the recommended/default or first option is genuinely safe.",
  "After clarify returns, details.answers = source of truth. Continue from answers.",
];

export default function clarifyExtension(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "clarify",
    label: "Clarify",
    description: DESCRIPTION,
    promptSnippet:
      "clarify — proactive 1-3 question user-decision tool for blocked preference/requirement/approval/direction cases",
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

      const result = await ctx.ui.custom<ClarifyResult>((tui, theme, _kb, done) =>
        createClarifyComponent(questions, tui, theme, done)
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
