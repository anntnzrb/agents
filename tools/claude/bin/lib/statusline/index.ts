#!/usr/bin/env bun

/**
 * Claude Code statusline generator
 */

import { die } from "../shared/process.ts";
import type { StatusLineData, EnrichedStatusLineData } from "./types.ts";
import { parseInput, logSession, readInput } from "./input.ts";
import { getDisplayPath } from "./display/path.ts";
import { buildStatusLine } from "./display/builder.ts";
import { countUserMessages } from "./transcript/messages.ts";
import { getTokenMetrics } from "./transcript/metrics.ts";

/**
 * Enrich parsed data with computed fields
 *
 * Takes parsed session data and enriches it with computed display path, message count, and token metrics.
 * Concurrently fetches git-aware directory path, counts quota-relevant user messages, and gets token metrics.
 *
 * @param data - Parsed status line data from JSON input
 * @param input - Raw input string for debugging/logging purposes
 * @returns Promise resolving to enriched data with computed fields
 */
const enrichData = async (
  data: Partial<StatusLineData>,
  input: string,
): Promise<EnrichedStatusLineData> => {
  logSession(input, data.session_id);
  const [cwd, msgCount, tokenMetrics] = await Promise.all([
    getDisplayPath(data.workspace, data.cwd),
    countUserMessages(data.transcript_path ?? ""),
    getTokenMetrics(data.transcript_path ?? ""),
  ]);
  return {
    session_id: data.session_id ?? "",
    transcript_path: data.transcript_path ?? "",
    cwd,
    model: data.model ?? { id: "", display_name: "Claude" },
    workspace: data.workspace ?? { current_dir: "", project_dir: "" },
    version: data.version ?? "",
    output_style: data.output_style ?? { name: "default" },
    cost: data.cost ?? {
      total_cost_usd: 0,
      total_duration_ms: 0,
      total_api_duration_ms: 0,
    },
    exceeds_200k_tokens: data.exceeds_200k_tokens ?? false,
    msgCount,
    tokenMetrics,
  };
};

/**
 * Main statusline generation pipeline
 *
 * Orchestrates the complete statusline generation process:
 * 1. Parse command line arguments
 * 2. Read input from file or stdin
 * 3. Parse JSON data with comment filtering
 * 4. Concurrently fetch display path and message count
 * 5. Build and output formatted status line
 *
 * @returns Promise that resolves when status line is written to stdout
 */
const main = () =>
  readInput(process.argv.slice(2))
    .then((input) => parseInput(input).then((data) => enrichData(data, input)))
    .then(buildStatusLine)
    .then(process.stdout.write.bind(process.stdout));

main().catch(die);
