/**
 * Question extraction helpers.
 */

import { complete, type UserMessage } from "@mariozechner/pi-ai";
import type { ExtensionContext } from "@mariozechner/pi-coding-agent";
import { BorderedLoader } from "@mariozechner/pi-coding-agent";
import { JSON_BLOCK_RE, SYSTEM_PROMPT } from "./constants.ts";
import type { ActiveModel, ExtractionResult } from "./types.ts";

/**
 * Parse the JSON response from the LLM.
 */
function parseExtractionResult(text: string): ExtractionResult | null {
  try {
    let jsonStr = text;
    const jsonMatch = text.match(JSON_BLOCK_RE);
    if (jsonMatch) {
      jsonStr = jsonMatch[1].trim();
    }

    const parsed = JSON.parse(jsonStr);
    if (parsed && Array.isArray(parsed.questions)) {
      return parsed as ExtractionResult;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Extract response text blocks.
 */
function extractResponseText(parts: readonly { type: string; text?: string }[]): string {
  return parts
    .filter((part): part is { type: "text"; text: string } => part.type === "text")
    .map((part) => part.text)
    .join("\n");
}

/**
 * Call the extraction model and parse the response.
 */
async function runExtraction(
  ctx: ExtensionContext,
  model: ActiveModel,
  assistantText: string,
  signal: AbortSignal
): Promise<ExtractionResult | null> {
  const apiKey = await ctx.modelRegistry.getApiKey(model);
  const userMessage: UserMessage = {
    role: "user",
    content: [{ type: "text", text: assistantText }],
    timestamp: Date.now(),
  };

  const response = await complete(
    model,
    { systemPrompt: SYSTEM_PROMPT, messages: [userMessage] },
    { apiKey, signal }
  );

  if (response.stopReason === "aborted") {
    return null;
  }

  return parseExtractionResult(extractResponseText(response.content));
}

/**
 * Extract questions from the assistant text.
 */
export function extractQuestions(
  ctx: ExtensionContext,
  model: ActiveModel,
  assistantText: string
): Promise<ExtractionResult | null> {
  return ctx.ui.custom<ExtractionResult | null>((tui, theme, _kb, done) => {
    const loader = new BorderedLoader(tui, theme, `Extracting questions using ${model.id}...`);
    loader.onAbort = () => done(null);

    runExtraction(ctx, model, assistantText, loader.signal)
      .then(done)
      .catch(() => done(null));

    return loader;
  });
}
