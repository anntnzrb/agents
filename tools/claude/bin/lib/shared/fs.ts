/**
 * File system utilities with safe error handling
 */

import { existsSync } from "fs";

/**
 * Wrap an async operation with a fallback value on error
 * @param operation - Promise to execute
 * @param fallback - Value to return on error
 * @returns Promise resolving to operation result or fallback on error
 */
export const withFallback = <T>(
  operation: Promise<T>,
  fallback: T,
): Promise<T> => operation.catch(() => fallback);

/**
 * Wrap an async operation with a fallback and optional warning
 * @param operation - Promise to execute
 * @param fallback - Value to return on error
 * @param warn - Warning message to log on error
 * @returns Promise resolving to operation result or fallback on error
 */
const withWarning = <T>(
  operation: Promise<T>,
  fallback: T,
  warn: string,
): Promise<T> =>
  operation.catch((err) => {
    console.warn(`${warn}: ${err}`);
    return fallback;
  });

/**
 * Safe file read with fallback to empty string on error
 * @param path - File system path to read from
 * @returns Promise resolving to file content or empty string on error
 */
export const safeRead = (path: string): Promise<string> =>
  existsSync(path)
    ? withFallback(Bun.file(path).text(), "")
    : Promise.resolve("");

/**
 * Safe file write with fallback to void on error
 * @param path - File system path to write to
 * @param content - Content to write
 * @returns Promise resolving to void or logging warning on error
 */
export const safeWrite = (path: string, content: string): Promise<void> =>
  withWarning(Bun.write(path, content), undefined, "File write failed");

/**
 * Safe file deletion with silent error handling
 * @param path - File system path to delete
 * @returns Promise that resolves when deletion completes or fails silently
 */
export const safeDelete = (path: string): Promise<void> =>
  existsSync(path)
    ? withFallback(Bun.file(path).delete(), undefined)
    : Promise.resolve();

/**
 * Parse JSONL file with custom line processor
 * @param path - Path to JSONL file
 * @param parseLine - Function to parse and filter each line
 * @returns Promise resolving to array of parsed results
 */
export const parseJsonlFile = async <T>(
  path: string,
  parseLine: (data: any) => T | null,
): Promise<T[]> => {
  const content = await safeRead(path);
  if (!content) return [];

  const results = content
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      try {
        return parseLine(JSON.parse(line));
      } catch {
        return null;
      }
    });

  return results.filter((r): r is T => r !== null);
};
