/**
 * Input handling and parsing utilities
 */

import { safeJsonParse } from "../shared/json.ts";
import type { StatusLineData } from "./types.ts";

/**
 * Parse JSON input string, filtering out comment lines starting with #
 * @param input - Raw JSON input string that may contain comments
 * @returns Promise resolving to parsed StatusLineData or partial object on parse error
 */
export const parseInput = (input: string): Promise<Partial<StatusLineData>> =>
  safeJsonParse<Partial<StatusLineData>>(input.replace(/^#.*/gm, ""));

/**
 * Log session input to temporary file for debugging
 * @param input - Raw input string to log
 * @param sessionId - Session identifier from parsed data
 * @returns Promise that resolves silently on success or failure
 */
export const logSession = (input: string, sessionId: string = "unknown") =>
  Bun.write(
    `/tmp/claude-statusline-${sessionId}.json`,
    `# JSON input captured on ${new Date().toISOString()}\n${input}\n`,
  ).catch((e) => console.debug?.("logSession failed:", e));

/**
 * Read JSON input from file argument or stdin
 * @param args - Command line arguments (first arg used as file path if provided)
 * @returns Promise resolving to input text content
 */
export const readInput = (args: string[]): Promise<string> =>
  args[0] ? Bun.file(args[0]).text() : new Response(Bun.stdin).text();
