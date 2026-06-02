import { promises as fs } from "node:fs";
import type { RawMatch } from "./logic.js";

export const GREP_MAX_LINE_LENGTH = 500;

const truncateLineForOutput = (
  line: string,
): { text: string; truncated: boolean } => {
  if (line.length <= GREP_MAX_LINE_LENGTH)
    return { text: line, truncated: false };
  return {
    text: `${line.slice(0, GREP_MAX_LINE_LENGTH)}... [truncated]`,
    truncated: true,
  };
};

const readFileLinesCached = async (
  cache: Map<string, string[]>,
  absolutePath: string,
): Promise<string[]> => {
  const existing = cache.get(absolutePath);
  if (existing) return existing;
  try {
    const content = await fs.readFile(absolutePath, "utf8");
    const lines = content
      .replace(/\r\n/g, "\n")
      .replace(/\r/g, "\n")
      .split("\n");
    cache.set(absolutePath, lines);
    return lines;
  } catch {
    cache.set(absolutePath, []);
    return [];
  }
};

export const formatMatches = async (
  matches: RawMatch[],
  contextLines: number,
): Promise<{ output: string; linesTruncated: boolean }> => {
  if (matches.length === 0) return { output: "", linesTruncated: false };
  let linesTruncated = false;
  const outputLines: string[] = [];
  const fileCache = new Map<string, string[]>();

  if (contextLines <= 0) {
    for (const match of matches) {
      const { text, truncated } = truncateLineForOutput(match.lineText);
      if (truncated) linesTruncated = true;
      outputLines.push(`${match.displayPath}:${match.lineNumber}: ${text}`);
    }
    return { output: outputLines.join("\n"), linesTruncated };
  }

  for (const match of matches) {
    const lines = await readFileLinesCached(fileCache, match.absolutePath);
    if (lines.length === 0) {
      outputLines.push(
        `${match.displayPath}:${match.lineNumber}: (unable to read file)`,
      );
      continue;
    }
    const start = Math.max(1, match.lineNumber - contextLines);
    const end = Math.min(lines.length, match.lineNumber + contextLines);
    for (let lineNumber = start; lineNumber <= end; lineNumber += 1) {
      const lineText = lines[lineNumber - 1] ?? "";
      const { text, truncated } = truncateLineForOutput(lineText);
      if (truncated) linesTruncated = true;
      if (lineNumber === match.lineNumber) {
        outputLines.push(`${match.displayPath}:${lineNumber}: ${text}`);
      } else {
        outputLines.push(`${match.displayPath}-${lineNumber}- ${text}`);
      }
    }
  }

  return { output: outputLines.join("\n"), linesTruncated };
};
