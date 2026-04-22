/**
 * Answer Extension - extracts questions from the last assistant response and collects answers.
 */

import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { ANSWER_MESSAGE_PREFIX } from "./constants.ts";
import { findLastAssistantText } from "./assistant-text.ts";
import { extractQuestions } from "./extraction.ts";
import { QnAComponent } from "./qna-component.ts";
import type { ActiveModel, ExtractedQuestion } from "./types.ts";

/**
 * Ensure UI and model are available for the /answer command.
 */
const ensureInteractiveModel = (
  ctx: ExtensionContext
): ctx is ExtensionContext & { model: ActiveModel } => {
  if (!ctx.hasUI) {
    ctx.ui.notify("answer requires interactive mode", "error");
    return false;
  }
  if (!ctx.model) {
    ctx.ui.notify("No model selected", "error");
    return false;
  }
  return true;
};

/**
 * Resolve the last assistant text or notify on failure.
 */
const resolveAssistantText = (ctx: ExtensionContext): string | null => {
  const result = findLastAssistantText(ctx.sessionManager.getBranch());
  if (result.status === "found") {
    return result.text;
  }
  if (result.status === "incomplete") {
    ctx.ui.notify(`Last assistant message incomplete (${result.reason})`, "error");
    return null;
  }
  ctx.ui.notify("No assistant messages found", "error");
  return null;
};

/**
 * Prompt the user to answer extracted questions.
 */
const collectAnswers = (
  ctx: ExtensionContext,
  questions: ExtractedQuestion[]
): Promise<string | null> => {
  return ctx.ui.custom<string | null>(
    (tui, _theme, _kb, done) => new QnAComponent(questions, tui, done)
  );
};

/**
 * Send the compiled answers as a custom message.
 */
const sendAnswers = (pi: ExtensionAPI, answers: string): void => {
  pi.sendMessage(
    {
      customType: "answers",
      content: `${ANSWER_MESSAGE_PREFIX}${answers}`,
      display: true,
    },
    { triggerTurn: true }
  );
};

/**
 * Handle /answer interactions.
 */
const answerHandler = async (pi: ExtensionAPI, ctx: ExtensionContext): Promise<void> => {
  if (!ensureInteractiveModel(ctx)) return;

  const assistantText = resolveAssistantText(ctx);
  if (!assistantText) return;

  const extractionResult = await extractQuestions(ctx, ctx.model, assistantText);
  if (extractionResult === null) {
    ctx.ui.notify("Cancelled", "info");
    return;
  }

  if (extractionResult.questions.length === 0) {
    ctx.ui.notify("No questions found in the last message", "info");
    return;
  }

  const answersResult = await collectAnswers(ctx, extractionResult.questions);
  if (answersResult === null) {
    ctx.ui.notify("Cancelled", "info");
    return;
  }

  sendAnswers(pi, answersResult);
};

/**
 * Register the /answer command.
 */
const answerExtension = (pi: ExtensionAPI): void => {
  pi.registerCommand("answer", {
    description: "Extract questions from last assistant message into interactive Q&A",
    handler: (_args, ctx) => answerHandler(pi, ctx),
  });
};

export default answerExtension;
