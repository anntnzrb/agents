/**
 * User message counting utilities
 */

import { parseJsonlFile } from "../../shared/fs.ts";

/**
 * Count actual user messages in Claude Code transcript file
 *
 * Parses JSONL transcript and counts only messages that are relevant for quota tracking.
 * Filters out tool results, meta messages, and system-generated content.
 *
 * @param path - Path to transcript JSONL file
 * @returns Promise resolving to number of quota-relevant user messages
 */
export const countUserMessages = async (path: string): Promise<number> => {
  if (!path) return 0;

  const results = await parseJsonlFile<boolean>(path, (entry) => {
    const msg = entry.message?.content || "";
    return entry.type === "user" &&
      !entry.toolUseResult &&
      !entry.isMeta &&
      ![
        "<command-name>",
        "<local-command-stdout>",
        "Caveat: The messages below",
      ].some((pattern) => msg.includes(pattern))
      ? true
      : null;
  });

  return results.length;
};
