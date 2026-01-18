/**
 * Token metrics extraction from transcript
 */

import { safeRead } from "../../shared/fs.ts";
import type { TokenMetrics } from "../types.ts";

/**
 * Get token metrics from Claude Code transcript file
 *
 * Parses JSONL transcript to find the most recent main chain message
 * and returns token metrics including context length.
 *
 * @param path - Path to transcript JSONL file
 * @returns Promise resolving to token metrics
 */
export const getTokenMetrics = async (path: string): Promise<TokenMetrics> => {
  if (!path) return { contextLength: 0 };

  const content = await safeRead(path);
  const lines = content
    .split("\n")
    .filter((line) => line.trim() && line.startsWith("{"));

  const entries = lines
    .map((line) => {
      try {
        const data = JSON.parse(line);
        return data.message?.usage &&
          data.isSidechain !== true &&
          data.timestamp
          ? data
          : null;
      } catch {
        return null;
      }
    })
    .filter((entry) => entry !== null);

  entries.sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  );

  const latest = entries.at(-1);
  return {
    contextLength: latest?.message?.usage
      ? (latest.message.usage.input_tokens ?? 0) +
        (latest.message.usage.cache_read_input_tokens ?? 0) +
        (latest.message.usage.cache_creation_input_tokens ?? 0)
      : 0,
  };
};
