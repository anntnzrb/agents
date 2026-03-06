import { readFileSync } from "node:fs";

import { parse, printParseErrorCode } from "jsonc-parser";

import type {
  BlockAction,
  CommandGuardConfig,
  ExecutableMatch,
  LoadConfigResult,
  MatchConfig,
  RegexMatch,
  Rule,
} from "./types";

const DEFAULT_CONFIG: CommandGuardConfig = {
  version: 1,
  agentBash: {
    rules: [],
  },
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  return value.every((item) => typeof item === "string") ? value : null;
}

function validateRegex(pattern: string, flags: string | undefined): string | null {
  try {
    void new RegExp(pattern, flags ?? "");
    return null;
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  }
}

function normalizeBlockAction(value: unknown, path: string): BlockAction | string {
  if (!isObject(value)) {
    return `${path} must be an object`;
  }

  if (value.type !== "block") {
    return `${path}.type must be \"block\"`;
  }

  if (typeof value.message !== "string" || value.message.trim().length === 0) {
    return `${path}.message must be a non-empty string`;
  }

  return {
    type: "block",
    message: value.message,
  };
}

function normalizeExecutableMatch(value: Record<string, unknown>, path: string): ExecutableMatch | string {
  const names = value.names === undefined ? [] : asStringArray(value.names);
  if (value.names !== undefined && names === null) {
    return `${path}.names must be an array of strings`;
  }

  const patterns = value.patterns === undefined ? [] : asStringArray(value.patterns);
  if (value.patterns !== undefined && patterns === null) {
    return `${path}.patterns must be an array of strings`;
  }

  if (names.length === 0 && patterns.length === 0) {
    return `${path} must define at least one name or pattern`;
  }

  if (value.flags !== undefined && typeof value.flags !== "string") {
    return `${path}.flags must be a string`;
  }

  if (value.caseSensitive !== undefined && typeof value.caseSensitive !== "boolean") {
    return `${path}.caseSensitive must be a boolean`;
  }

  for (const [index, pattern] of patterns.entries()) {
    const error = validateRegex(pattern, value.flags as string | undefined);
    if (error) {
      return `${path}.patterns[${index}] is invalid: ${error}`;
    }
  }

  return {
    type: "executable",
    names,
    patterns,
    flags: value.flags as string | undefined,
    caseSensitive: value.caseSensitive as boolean | undefined,
  };
}

function normalizeRegexMatch(value: Record<string, unknown>, path: string): RegexMatch | string {
  if (typeof value.pattern !== "string" || value.pattern.length === 0) {
    return `${path}.pattern must be a non-empty string`;
  }

  if (value.flags !== undefined && typeof value.flags !== "string") {
    return `${path}.flags must be a string`;
  }

  const error = validateRegex(value.pattern, value.flags as string | undefined);
  if (error) {
    return `${path}.pattern is invalid: ${error}`;
  }

  return {
    type: "regex",
    pattern: value.pattern,
    flags: value.flags as string | undefined,
  };
}

function normalizeMatch(value: unknown, path: string): MatchConfig | string {
  if (!isObject(value)) {
    return `${path} must be an object`;
  }

  if (value.type === "executable") {
    return normalizeExecutableMatch(value, path);
  }

  if (value.type === "regex") {
    return normalizeRegexMatch(value, path);
  }

  return `${path}.type must be \"executable\" or \"regex\"`;
}

function normalizeRule(value: unknown, index: number): Rule | string {
  const path = `agentBash.rules[${index}]`;
  if (!isObject(value)) {
    return `${path} must be an object`;
  }

  if (value.id !== undefined && typeof value.id !== "string") {
    return `${path}.id must be a string`;
  }

  const match = normalizeMatch(value.match, `${path}.match`);
  if (typeof match === "string") {
    return match;
  }

  const action = normalizeBlockAction(value.action, `${path}.action`);
  if (typeof action === "string") {
    return action;
  }

  return {
    id: value.id as string | undefined,
    match,
    action,
  };
}

function normalizeConfig(value: unknown): CommandGuardConfig | string {
  if (!isObject(value)) {
    return "config root must be an object";
  }

  if (value.version !== undefined && value.version !== 1) {
    return "version must be 1";
  }

  const agentBash = value.agentBash === undefined ? {} : value.agentBash;
  if (!isObject(agentBash)) {
    return "agentBash must be an object";
  }

  const rulesValue = agentBash.rules === undefined ? [] : agentBash.rules;
  if (!Array.isArray(rulesValue)) {
    return "agentBash.rules must be an array";
  }

  const rules: Rule[] = [];
  for (const [index, entry] of rulesValue.entries()) {
    const normalized = normalizeRule(entry, index);
    if (typeof normalized === "string") {
      return normalized;
    }
    rules.push(normalized);
  }

  return {
    version: 1,
    agentBash: { rules },
  };
}

function formatJsoncError(path: string, offset: number, code: number): string {
  const label = printParseErrorCode(code);
  return `command guard config invalid at ${path} (offset ${offset}, ${label})`;
}

export function loadConfig(path: string): LoadConfigResult {
  let raw: string;
  try {
    raw = readFileSync(path, "utf8");
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      reason: `command guard configuration unavailable at ${path}: ${detail}`,
    };
  }

  const errors: { error: number; offset: number }[] = [];
  const parsed = parse(raw, errors, {
    allowTrailingComma: true,
    disallowComments: false,
  });

  if (errors.length > 0) {
    const first = errors[0];
    return {
      ok: false,
      reason: formatJsoncError(path, first.offset, first.error),
    };
  }

  const normalized = normalizeConfig(parsed ?? DEFAULT_CONFIG);
  if (typeof normalized === "string") {
    return {
      ok: false,
      reason: `command guard configuration invalid at ${path}: ${normalized}`,
    };
  }

  return {
    ok: true,
    config: normalized,
  };
}
