/**
 * JSON parsing and file utilities with safe error handling
 */

import { safeRead, withFallback } from "./fs.ts";

/**
 * Safely parse JSON string, returning empty object on error
 * @param jsonStr - JSON string to parse
 * @returns Promise resolving to parsed object or empty object on parse error
 */
export const safeJsonParse = <T = unknown>(jsonStr: string): Promise<T> =>
  withFallback(Promise.resolve(jsonStr).then(JSON.parse), {} as T);

/**
 * Safely read and parse JSON file
 * @param path - File system path to JSON file
 * @returns Promise resolving to parsed JSON object or empty object on error
 */
export const safeJsonRead = <T = unknown>(path: string): Promise<T> =>
  safeRead(path).then((content) =>
    content ? safeJsonParse<T>(content) : ({} as T),
  );

/**
 * Safely write JSON data to file
 * @param path - File system path to write to
 * @param data - Data to serialize and write
 * @returns Promise that resolves when write completes or fails silently
 */
export const safeJsonWrite = (path: string, data: unknown): Promise<void> =>
  withFallback(Bun.write(path, JSON.stringify(data, null, 2)), undefined);
