import { promises as fs } from "node:fs";
import { Effect } from "effect";
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

const readFileLinesCachedEffect = Effect.fn("readFileLinesCached")(function*(
  cache: Map<string, string[]>,
  absolutePath: string,
): Effect.fn.Return<string[]> {
  const existing = cache.get(absolutePath);
  if (existing) return existing;
  const lines = yield* Effect.tryPromise({
    try: () => fs.readFile(absolutePath, "utf8"),
    catch: () => "",
  }).pipe(
    Effect.map((content) =>
      content
        .replace(/\r\n/g, "\n")
        .replace(/\r/g, "\n")
        .split("\n"),
    ),
    Effect.orElseSucceed(() => []),
  );
  cache.set(absolutePath, lines);
  return lines;
});

export const formatMatchesEffect = Effect.fn("formatMatches")(function*(
  matches: RawMatch[],
  contextLines: number,
): Effect.fn.Return<{ output: string; linesTruncated: boolean }, never> {
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
    const lines = yield* readFileLinesCachedEffect(fileCache, match.absolutePath);
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
});

export const formatMatches = (
  matches: RawMatch[],
  contextLines: number,
): Promise<{ output: string; linesTruncated: boolean }> =>
  Effect.runPromise(formatMatchesEffect(matches, contextLines));
