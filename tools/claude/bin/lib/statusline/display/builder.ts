/**
 * Status line builder
 */

import type { EnrichedStatusLineData } from "../types.ts";
import { colors } from "./colors.ts";
import { formatters } from "./formatters.ts";

/**
 * Build formatted status line with ANSI colors and emojis
 *
 * Creates a comprehensive status display showing model info, directory, message count,
 * code changes, cost information, and context warnings. Uses organized formatters
 * for consistent presentation across all status components.
 *
 * @param data - Enriched status data with computed fields
 * @returns Formatted status line string with ANSI escape codes and newline
 */
export const buildStatusLine = (data: EnrichedStatusLineData) =>
  [
    // Version
    `${colors.dim}${formatters.version(data.version)}${colors.reset}`,
    // Model
    `🧠 ${formatters.model(data.model)}`,
    // Style
    formatters.style(data.output_style),
    // Directory
    `@ ${colors.cyan}📁 ${data.cwd}${colors.reset}`,
    // Message count
    formatters.messageCount(data.msgCount),
    // Context length
    formatters.contextLength(data.tokenMetrics),
    // Cost
    `${colors.lightGreen}${formatters.cost(data.cost)}${colors.reset}`,
    // Context warning
    formatters.contextWarning(data.exceeds_200k_tokens),
  ]
    .filter(Boolean)
    .join(" ") + "\n";
