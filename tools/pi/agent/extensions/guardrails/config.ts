import { readFileSync } from "node:fs";

import type {
  BlockAction,
  ExecutableMatch,
  GuardrailsConfig,
  LoadConfigResult,
  MatchConfig,
  ProtectedPathRule,
  RegexMatch,
  Rule,
} from "./types.js";

const DEFAULT_CONFIG: GuardrailsConfig = {
  version: 1,
  agentBash: {
    rules: [],
  },
  protectedPaths: {
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
    return `${path}.type must be "block"`;
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
  const namesValue = value.names === undefined ? [] : asStringArray(value.names);
  if (value.names !== undefined && namesValue === null) {
    return `${path}.names must be an array of strings`;
  }
  const names = namesValue ?? [];

  const patternsValue = value.patterns === undefined ? [] : asStringArray(value.patterns);
  if (value.patterns !== undefined && patternsValue === null) {
    return `${path}.patterns must be an array of strings`;
  }
  const patterns = patternsValue ?? [];

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

  return `${path}.type must be "executable" or "regex"`;
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

function normalizeProtectedPathRule(value: unknown, index: number): ProtectedPathRule | string {
  const path = `protectedPaths.rules[${index}]`;
  if (!isObject(value)) {
    return `${path} must be an object`;
  }

  if (value.id !== undefined && typeof value.id !== "string") {
    return `${path}.id must be a string`;
  }

  if (typeof value.pattern !== "string" || value.pattern.trim().length === 0) {
    return `${path}.pattern must be a non-empty string`;
  }

  const tools = asStringArray(value.tools);
  if (tools === null || tools.length === 0) {
    return `${path}.tools must be a non-empty array of strings`;
  }

  for (const [toolIndex, tool] of tools.entries()) {
    if (tool !== "read" && tool !== "write" && tool !== "edit") {
      return `${path}.tools[${toolIndex}] must be read, write, or edit`;
    }
  }

  const action = normalizeBlockAction(value.action, `${path}.action`);
  if (typeof action === "string") {
    return action;
  }

  return {
    id: value.id as string | undefined,
    pattern: value.pattern.trim(),
    tools: tools as Array<"read" | "write" | "edit">,
    action,
  };
}

function normalizeConfig(value: unknown): GuardrailsConfig | string {
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

  const bashRulesValue = agentBash.rules === undefined ? [] : agentBash.rules;
  if (!Array.isArray(bashRulesValue)) {
    return "agentBash.rules must be an array";
  }

  const bashRules: Rule[] = [];
  for (const [index, entry] of bashRulesValue.entries()) {
    const normalized = normalizeRule(entry, index);
    if (typeof normalized === "string") {
      return normalized;
    }
    bashRules.push(normalized);
  }

  const protectedPaths = value.protectedPaths === undefined ? {} : value.protectedPaths;
  if (!isObject(protectedPaths)) {
    return "protectedPaths must be an object";
  }

  const protectedPathRulesValue = protectedPaths.rules === undefined ? [] : protectedPaths.rules;
  if (!Array.isArray(protectedPathRulesValue)) {
    return "protectedPaths.rules must be an array";
  }

  const protectedPathRules: ProtectedPathRule[] = [];
  for (const [index, entry] of protectedPathRulesValue.entries()) {
    const normalized = normalizeProtectedPathRule(entry, index);
    if (typeof normalized === "string") {
      return normalized;
    }
    protectedPathRules.push(normalized);
  }

  return {
    version: 1,
    agentBash: { rules: bashRules },
    protectedPaths: { rules: protectedPathRules },
  };
}

function stripJsonc(raw: string): string {
  let cleaned = raw.replace(/\/\/.*$/gm, "");
  cleaned = cleaned.replace(/\/\*[\s\S]*?\*\//g, "");
  cleaned = cleaned.replace(/,\s*([\]\}])/g, "$1");
  return cleaned;
}

export function loadConfig(path: string): LoadConfigResult {
  let raw: string;
  try {
    raw = readFileSync(path, "utf8");
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      reason: `guardrails configuration unavailable at ${path}: ${detail}`,
    };
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(stripJsonc(raw));
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      reason: `guardrails config invalid at ${path}: ${detail}`,
    };
  }

  const normalized = normalizeConfig(parsed ?? DEFAULT_CONFIG);
  if (typeof normalized === "string") {
    return {
      ok: false,
      reason: `guardrails configuration invalid at ${path}: ${normalized}`,
    };
  }

  return {
    ok: true,
    config: normalized,
  };
}
