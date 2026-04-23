import type { BashAction, ExecutableMatch, GuardrailsConfig, Rule } from "./types.js";

import { executableBasename, splitShellSegments, tokenizeCommand, unique } from "./shell.js";
import { firstExecutableIndex, unwrapCommand } from "./wrappers.js";

const MAX_NESTING_DEPTH = 8;

const CONTENT_SEARCH_EXECUTABLES = new Set([
  "rg",
  "ripgrep",
  "ag",
  "ack",
  "ack-grep",
  "pt",
  "ugrep",
  "sift",
  "grep",
  "ggrep",
  "findstr",
  "select-string",
]);

const FILE_DISCOVERY_EXECUTABLES = new Set([
  "fd",
  "fdfind",
  "fd-find",
  "find",
  "gfind",
  "locate",
  "mlocate",
  "plocate",
]);

const RG_OPTIONS_WITH_VALUE = new Set([
  "-e",
  "-f",
  "-g",
  "-m",
  "-A",
  "-B",
  "-C",
  "-j",
  "-t",
  "-T",
  "--glob",
  "--max-count",
  "--threads",
  "--type",
  "--type-not",
]);

const GREP_OPTIONS_WITH_VALUE = new Set(["-e", "-f", "-m", "-A", "-B", "-C", "--max-count"]);

const FD_OPTIONS_WITH_VALUE = new Set([
  "-g",
  "-d",
  "-t",
  "-E",
  "--glob",
  "--max-depth",
  "--type",
  "--exclude",
  "--search-path",
]);

const FIND_OPTIONS_WITH_VALUE = new Set([
  "-maxdepth",
  "-mindepth",
  "-name",
  "-path",
  "-type",
  "-mtime",
  "-mmin",
  "-size",
  "-user",
  "-group",
  "-perm",
]);

const EXECUTABLE_PATTERN_REGEX_CACHE = new WeakMap<ExecutableMatch, RegExp[]>();
const RULE_REGEX_CACHE = new WeakMap<Rule, RegExp>();

type ParsedCommand = {
  command: string;
  executable: string;
  tokens: string[];
};

interface Inspection {
  commands: string[];
  executables: string[];
  parsedCommands: ParsedCommand[];
}

interface RuleMatchContext {
  command: string;
  parsed?: ParsedCommand;
}

function normalizeExecutable(value: string): string {
  return executableBasename(value).toLowerCase();
}

function mergeInspection(...inspections: Inspection[]): Inspection {
  const commandSet = new Set<string>();
  const executableSet = new Set<string>();
  const parsedMap = new Map<string, ParsedCommand>();

  for (const inspection of inspections) {
    for (const command of inspection.commands) {
      commandSet.add(command);
    }
    for (const executable of inspection.executables) {
      executableSet.add(executable);
    }
    for (const parsed of inspection.parsedCommands) {
      const key = `${parsed.executable}\u0000${parsed.command}`;
      if (!parsedMap.has(key)) {
        parsedMap.set(key, parsed);
      }
    }
  }

  return {
    commands: [...commandSet],
    executables: [...executableSet],
    parsedCommands: [...parsedMap.values()],
  };
}

function emptyInspection(): Inspection {
  return { commands: [], executables: [], parsedCommands: [] };
}

function inspectCommand(command: string, depth = 0): Inspection {
  if (depth > MAX_NESTING_DEPTH) {
    return emptyInspection();
  }

  const parts: Inspection[] = [];
  const trimmed = command.trim();
  if (trimmed.length > 0) {
    parts.push({ commands: [trimmed], executables: [], parsedCommands: [] });
  }

  for (const segment of splitShellSegments(command)) {
    parts.push(inspectSegment(segment, depth));
  }

  return mergeInspection(...parts);
}

function inspectSegment(segment: string, depth: number): Inspection {
  const tokens = tokenizeCommand(segment);
  if (tokens.length === 0) {
    return emptyInspection();
  }

  return inspectTokens(tokens, segment, depth);
}

function inspectTokens(tokens: string[], command: string, depth: number): Inspection {
  if (depth > MAX_NESTING_DEPTH || tokens.length === 0) {
    return emptyInspection();
  }

  const index = firstExecutableIndex(tokens);
  if (index >= tokens.length) {
    return emptyInspection();
  }

  const executable = tokens[index];
  const normalizedExecutable = normalizeExecutable(executable);
  const current: Inspection = {
    commands: [command],
    executables: [executable, normalizedExecutable],
    parsedCommands: [
      {
        command,
        executable,
        tokens: tokens.slice(index),
      },
    ],
  };

  const unwrapped = unwrapCommand(tokens, index);
  const children: Inspection[] = [current];

  for (const nestedCommand of unwrapped.nestedCommands ?? []) {
    children.push(inspectCommand(nestedCommand, depth + 1));
  }

  if (unwrapped.remainderTokens && unwrapped.remainderTokens.length > 0) {
    children.push(inspectTokens(unwrapped.remainderTokens, unwrapped.remainderTokens.join(" "), depth + 1));
  }

  return mergeInspection(...children);
}

function buildFlags(flags: string | undefined, caseSensitive: boolean | undefined): string {
  if (caseSensitive !== false) {
    return flags ?? "";
  }
  return flags?.includes("i") ? flags : `${flags ?? ""}i`;
}

function getExecutablePatternRegexes(match: ExecutableMatch): RegExp[] {
  const cached = EXECUTABLE_PATTERN_REGEX_CACHE.get(match);
  if (cached) return cached;

  const flags = buildFlags(match.flags, match.caseSensitive);
  const compiled = (match.patterns ?? []).map((pattern) => new RegExp(pattern, flags));
  EXECUTABLE_PATTERN_REGEX_CACHE.set(match, compiled);
  return compiled;
}

function getRuleRegex(rule: Rule): RegExp {
  const cached = RULE_REGEX_CACHE.get(rule);
  if (cached) return cached;

  if (rule.match.type !== "regex") {
    throw new Error("getRuleRegex called for non-regex rule");
  }

  const regex = new RegExp(rule.match.pattern, rule.match.flags ?? "");
  RULE_REGEX_CACHE.set(rule, regex);
  return regex;
}

function matchExecutable(actual: string, match: ExecutableMatch): boolean {
  const names = match.names ?? [];
  const basename = executableBasename(actual);
  const values = [actual, basename, normalizeExecutable(actual)];

  for (const name of names) {
    const normalizedName = match.caseSensitive === false ? name.toLowerCase() : name;
    for (const value of values) {
      const subject = match.caseSensitive === false ? value.toLowerCase() : value;
      if (name.includes("/") || name.includes("\\")) {
        if (subject === normalizedName) {
          return true;
        }
      } else if (subject === normalizedName || executableBasename(subject) === normalizedName) {
        return true;
      }
    }
  }

  const regexes = getExecutablePatternRegexes(match);
  for (const regex of regexes) {
    if (values.some((value) => regex.test(value))) {
      return true;
    }
  }

  return false;
}

function getRuleMatches(inspection: Inspection, rule: Rule): RuleMatchContext[] {
  const match = rule.match;
  if (match.type === "regex") {
    const regex = getRuleRegex(rule);
    return inspection.commands.filter((command) => regex.test(command)).map((command) => ({ command }));
  }

  const matches: RuleMatchContext[] = [];
  for (const parsed of inspection.parsedCommands) {
    if (matchExecutable(parsed.executable, match)) {
      matches.push({ command: parsed.command, parsed });
    }
  }
  return matches;
}

function isInfoFlag(token: string): boolean {
  return token === "-h" || token === "--help" || token === "-V" || token === "--version";
}

function isRootLikePath(token: string): boolean {
  const normalized = token.trim();
  if (normalized.length === 0) return false;
  if (normalized === "." || normalized === "./" || normalized === "/" || normalized === "~" || normalized === "~/") {
    return true;
  }
  if (/^[A-Za-z]:[\\/]?$/.test(normalized)) return true;
  return false;
}

function optionHasValue(token: string, executable: string): boolean {
  const normalized = normalizeExecutable(executable);
  if (normalized === "rg" || normalized === "ripgrep") {
    return RG_OPTIONS_WITH_VALUE.has(token);
  }
  if (normalized === "grep" || normalized === "ggrep") {
    return GREP_OPTIONS_WITH_VALUE.has(token);
  }
  if (normalized === "fd" || normalized === "fdfind" || normalized === "fd-find") {
    return FD_OPTIONS_WITH_VALUE.has(token);
  }
  if (normalized === "find" || normalized === "gfind") {
    return FIND_OPTIONS_WITH_VALUE.has(token);
  }
  return false;
}

function extractPositionals(parsed: ParsedCommand): string[] {
  const args = parsed.tokens.slice(1);
  const positionals: string[] = [];

  for (let i = 0; i < args.length; i += 1) {
    const token = args[i];
    if (token === "--") {
      positionals.push(...args.slice(i + 1));
      break;
    }
    if (token.startsWith("-")) {
      if (token.includes("=") || !optionHasValue(token, parsed.executable)) {
        continue;
      }
      i += 1;
      continue;
    }
    positionals.push(token);
  }

  return positionals;
}

function parseMaxDepth(parsed: ParsedCommand): number | undefined {
  const args = parsed.tokens.slice(1);
  for (let i = 0; i < args.length; i += 1) {
    const token = args[i];
    if (token === "-maxdepth" && i + 1 < args.length) {
      const value = Number.parseInt(args[i + 1], 10);
      return Number.isFinite(value) ? value : undefined;
    }
    if (token.startsWith("-maxdepth=") || token.startsWith("--maxdepth=")) {
      const value = Number.parseInt(token.split("=")[1] ?? "", 10);
      return Number.isFinite(value) ? value : undefined;
    }
  }
  return undefined;
}

function shouldWarnContentSearch(parsed: ParsedCommand): boolean {
  const executable = normalizeExecutable(parsed.executable);
  const args = parsed.tokens.slice(1);
  if (args.some(isInfoFlag)) return false;

  if (executable === "git") {
    const tokens = tokenizeCommand(parsed.command);
    const grepIndex = tokens.findIndex((token) => token.toLowerCase() === "grep");
    if (grepIndex === -1) return false;

    const grepArgs = tokens.slice(grepIndex + 1);
    if (grepArgs.some(isInfoFlag)) return false;
    return true;
  }

  return CONTENT_SEARCH_EXECUTABLES.has(executable);
}

function shouldWarnFileDiscovery(parsed: ParsedCommand): boolean {
  const executable = normalizeExecutable(parsed.executable);
  const args = parsed.tokens.slice(1);
  if (args.some(isInfoFlag)) return false;

  if (executable === "fd" || executable === "fdfind" || executable === "fd-find") {
    const positionals = extractPositionals(parsed);
    const paths = positionals.slice(1);
    if (paths.length === 0) return true;
    return paths.some((token) => isRootLikePath(token) || token === "**" || token === "*");
  }

  if (executable === "find" || executable === "gfind") {
    const positionals = extractPositionals(parsed);
    const startPaths = positionals.filter((token) => !token.startsWith("-")).slice(0, 1);
    const roots = startPaths.length === 0 ? ["."] : startPaths;
    const rootLike = roots.some((token) => isRootLikePath(token));
    if (!rootLike) return false;
    const maxDepth = parseMaxDepth(parsed);
    if (maxDepth !== undefined && maxDepth <= 2) return false;
    return true;
  }

  if (executable === "locate" || executable === "mlocate" || executable === "plocate") {
    const positionals = extractPositionals(parsed);
    const query = positionals[0] ?? "";
    return query.length < 3 || query === "*";
  }

  return FILE_DISCOVERY_EXECUTABLES.has(executable);
}

function shouldEmitWarn(rule: Rule, context: RuleMatchContext): boolean {
  if (rule.action.type !== "warn") return true;
  const ruleId = rule.id ?? "";

  if (ruleId === "prefer-native-content-search" || ruleId === "prefer-native-content-search-git-grep") {
    return context.parsed ? shouldWarnContentSearch(context.parsed) : shouldWarnContentSearch({
      command: context.command,
      executable: tokenizeCommand(context.command)[0] ?? "",
      tokens: tokenizeCommand(context.command),
    });
  }

  if (ruleId === "prefer-native-file-discovery") {
    if (!context.parsed) {
      const tokens = tokenizeCommand(context.command);
      return shouldWarnFileDiscovery({
        command: context.command,
        executable: tokens[0] ?? "",
        tokens,
      });
    }
    return shouldWarnFileDiscovery(context.parsed);
  }

  return true;
}

export function actionForCommand(command: string, config: GuardrailsConfig): BashAction | null {
  const inspection = inspectCommand(command);

  for (const rule of config.agentBash.rules) {
    const matches = getRuleMatches(inspection, rule);
    if (matches.length === 0) continue;

    const warnMatch = matches.find((context) => shouldEmitWarn(rule, context));
    if (warnMatch) {
      return rule.action;
    }
  }

  return null;
}

export function reasonForCommand(command: string, config: GuardrailsConfig): string | null {
  const action = actionForCommand(command, config);
  return action ? action.message : null;
}

export const __test = {
  extractPositionals,
  parseMaxDepth,
  shouldWarnContentSearch,
  shouldWarnFileDiscovery,
  inspectCommand,
  normalizeExecutable,
  optionHasValue,
  unique,
};
