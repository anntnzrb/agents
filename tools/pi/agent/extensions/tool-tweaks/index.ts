/**
 * Tool Output Suppressor - hides tool parameters and results in the UI.
 */

import { createCodingTools, createReadOnlyTools } from "@mariozechner/pi-coding-agent";
import type { ExtensionAPI, Theme } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";
import { Option } from "effect";
import { pipe } from "effect/Function";

type Tool = ReturnType<typeof createCodingTools>[number];
type ToolArgs = Record<string, unknown>;
const tools = (() => {
  const map = new Map<string, Tool>();
  // biome-ignore lint/correctness/noProcessGlobal: Node-only extension.
  const cwd = process.cwd();
  for (const tool of createCodingTools(cwd)) {
    map.set(tool.name, tool);
  }
  for (const tool of createReadOnlyTools(cwd)) {
    map.set(tool.name, tool);
  }
  return [...map.values()];
})();

const MAX_CALL_LENGTH = 180;
const MAX_ARG_VALUE_LENGTH = 120;

const countUnescapedQuotes = (text: string): number => {
  let count = 0;
  let escaped = false;
  for (const char of text) {
    if (escaped) {
      escaped = false;
      continue;
    }
    if (char === "\\") {
      escaped = true;
      continue;
    }
    if (char === "\"") count += 1;
  }
  return count;
};

const trimTrailingBackslashes = (text: string): string => {
  let trimmed = text;
  while (trimmed.endsWith("\\")) {
    trimmed = trimmed.slice(0, -1);
  }
  return trimmed;
};

const endsWithUnescapedQuote = (text: string): boolean => {
  if (!text.endsWith("\"")) return false;
  let backslashes = 0;
  for (let index = text.length - 2; index >= 0 && text[index] === "\\"; index -= 1) {
    backslashes += 1;
  }
  return backslashes % 2 === 0;
};

/** Truncate the args line to the max length. */
const truncateArgs = (text: string, maxLength: number): string => {
  if (!(maxLength > 1 && text.length > maxLength)) return text;
  if (maxLength <= 2) return "…";

  let slice = text.slice(0, maxLength - 1);
  if (countUnescapedQuotes(slice) % 2 === 0) {
    if (endsWithUnescapedQuote(slice)) {
      const trimmed = trimTrailingBackslashes(slice.slice(0, -1));
      return `${trimmed}…"`;
    }
    return `${slice}…`;
  }

  slice = trimTrailingBackslashes(text.slice(0, maxLength - 2));
  return `${slice}…"`;
};

/** Truncate a single arg value. */
const truncateValue = (text: string): string =>
  text.length > MAX_ARG_VALUE_LENGTH
    ? `${text.slice(0, MAX_ARG_VALUE_LENGTH - 1)}…`
    : text;

/** Format a value for display in the call line. */
const formatValue = (value: unknown): string => {
  if (typeof value === "string") return JSON.stringify(truncateValue(value));
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const preview = value.slice(0, 3).map(formatValue).join(", ");
    return `[${preview}${value.length > 3 ? ", …" : ""}]`;
  }
  if (value && typeof value === "object") return "{…}";
  return "";
};

/** Format a single key/value pair for display. */
const formatArgEntry = (key: string, value: unknown): string | undefined =>
  pipe(
    Option.fromNullable(value),
    Option.map(formatValue),
    Option.filter((text) => text.length > 0),
    Option.match({
      onNone: () => undefined,
      onSome: (text) => `${key}: ${text}`,
    }),
  );

/** Format tool args into a compact string. */
const formatArgs = (args: ToolArgs): string | undefined => {
  const entries: string[] = [];
  for (const key in args) {
    if (!Object.hasOwn(args, key)) continue;
    const entry = formatArgEntry(key, args[key]);
    if (entry) entries.push(entry);
  }
  return entries.length > 0 ? entries.join(", ") : undefined;
};

/** Apply color styling to key/value args. */
const colorizeArgs = (argsText: string, theme: Theme): string => {
  const parts = argsText.split(", ");
  const colored = parts.map((part) => {
    const sepIndex = part.indexOf(": ");
    if (sepIndex < 0) {
      return theme.fg("toolOutput", theme.italic(part));
    }
    const key = part.slice(0, sepIndex);
    const value = part.slice(sepIndex + 2);
    return theme.fg("accent", key) + theme.fg("muted", ": ") +
      theme.fg("toolOutput", theme.italic(value));
  });
  return theme.fg("muted", "{ ") + colored.join(theme.fg("muted", ", ")) +
    theme.fg("muted", " }");
};

/** Render the minimal tool call header. */
const renderHiddenCall = (toolName: string, args: ToolArgs, theme: Theme) => {
  const argsText = formatArgs(args);
  const titleText = toolName;

  if (!argsText) {
    return new Text(theme.fg("toolTitle", titleText), 0, 0);
  }

  const maxArgsLength = Math.max(0, MAX_CALL_LENGTH - (titleText.length + 3));
  if (maxArgsLength <= 0) {
    return new Text(theme.fg("toolTitle", toolName), 0, 0);
  }

  const truncatedArgs = truncateArgs(argsText, maxArgsLength);
  const styledArgs = colorizeArgs(truncatedArgs, theme);
  const styled = `${theme.fg("toolTitle", titleText)} ${styledArgs}`;
  return new Text(styled, 0, 0);
};

/** Render a minimal pending indicator while the tool is running. */
const renderHiddenResult = (isPartial: boolean, theme: Theme) =>
  (isPartial ? new Text(theme.fg("muted", "…"), 0, 0) : undefined);

/** Register the tool output suppression renderers. */
export default function hideToolOutputExtension(pi: ExtensionAPI): void {
  for (const tool of tools) {
    pi.registerTool({
      name: tool.name,
      label: tool.label,
      description: tool.description,
      parameters: tool.parameters,
      execute: (toolCallId, params, onUpdate, _ctx, signal) =>
        tool.execute(toolCallId, params, signal, onUpdate),
      renderCall: (args, theme) => renderHiddenCall(tool.name, args as ToolArgs, theme),
      renderResult: (_result, options, theme) => renderHiddenResult(options.isPartial, theme),
    });
  }
}
