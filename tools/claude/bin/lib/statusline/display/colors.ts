/**
 * ANSI color codes for terminal formatting
 */

export const colors = {
  /** Dim/faded text color */
  dim: "\x1b[2m",
  /** Cyan color for directory paths */
  cyan: "\x1b[36m",
  /** Green color */
  green: "\x1b[32m",
  /** Light green color for cost display */
  lightGreen: "\x1b[92m",
  /** Red color */
  red: "\x1b[31m",
  /** Reset all formatting */
  reset: "\x1b[0m",
} as const;
