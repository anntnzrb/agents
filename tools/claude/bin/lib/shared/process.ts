/**
 * Process and error handling utilities
 */

/**
 * Log error message to stderr and exit process with failure code
 * @param msg - Error message or Error object to display
 * @returns Never returns (process exits)
 */
export const die = (msg: string | Error): never => (
  console.error(`Error: ${msg instanceof Error ? msg.message : msg}`),
  process.exit(1)
);
