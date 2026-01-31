/**
 * Helpers for extracting the last assistant message from the session.
 */

import type { SessionEntry } from "@mariozechner/pi-coding-agent";

/**
 * Result of searching for the last assistant message.
 */
export type AssistantTextResult =
  | { status: "found"; text: string }
  | { status: "incomplete"; reason: string }
  | { status: "missing" };

/**
 * Join all text parts in a message into one string.
 */
function extractMessageText(parts: readonly { type: string; text?: string }[]): string | null {
  const textParts = parts
    .filter((part): part is { type: "text"; text: string } => part.type === "text")
    .map((part) => part.text);
  return textParts.length > 0 ? textParts.join("\n") : null;
}

/**
 * Find the most recent assistant text in the branch.
 */
export function findLastAssistantText(entries: readonly SessionEntry[]): AssistantTextResult {
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i];
    if (entry.type !== "message") continue;
    const msg = entry.message;
    if (!("role" in msg) || msg.role !== "assistant") continue;
    if (msg.stopReason !== "stop") {
      return { status: "incomplete", reason: msg.stopReason };
    }
    const text = extractMessageText(msg.content);
    if (text) {
      return { status: "found", text };
    }
  }

  return { status: "missing" };
}
