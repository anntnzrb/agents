import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";
import { ClarifyParamsSchema, type ClarifyResult } from "./models.js";
import { buildSuccessText, normalizeQuestions, sortAnswers, validateQuestions } from "./results.js";
import { createClarifyComponent, renderCallText, renderResultText } from "./ui.js";

const DESCRIPTION = [
	"Interactively ask the user for missing requirements, preferences, approvals, or constraints.",
	"Use proactively when progress is blocked on something only the user can decide.",
	"Ask 1 focused question by default; ask 2-3 only when all answers are required before continuing.",
	"Prefer explicit options when you can suggest likely choices, and allow custom input unless you truly need a closed set.",
	"Do not use for facts you can discover from the repo, logs, docs, or tools.",
	"Interactive sessions only; non-interactive runs return a clean error instead of guessing.",
].join(" ");

const PROMPT_GUIDELINES = [
	"When blocked on user intent, preference, requirement, or approval, call clarify instead of guessing.",
	"Keep clarify short: 1 question if possible, max 3.",
	"Each question should target one decision and be immediately answerable.",
	"If likely choices are known, provide options with short descriptions and leave allowOther enabled unless the choice must be closed.",
	"After clarify returns, use details.answers as the structured source of truth.",
];

export default function clarifyExtension(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "clarify",
		label: "Clarify",
		description: DESCRIPTION,
		promptSnippet: "clarify — interactively ask the user 1-3 focused requirement/preference questions when blocked on user input",
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

			const result = await ctx.ui.custom<ClarifyResult>((tui, theme, _kb, done) =>
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
			const text = details ? renderResultText(details) : result.content[0]?.type === "text" ? result.content[0].text : "";
			const color = details?.cancelled ? "warning" : "success";
			return new Text(theme.fg(color, text), 0, 0);
		},
	});
}
