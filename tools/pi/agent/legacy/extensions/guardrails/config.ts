import { readFileSync } from "node:fs";

import type {
  BashAction,
  BlockAction,
  ExecutableMatch,
  GuardrailsConfig,
  LoadConfigResult,
  MatchConfig,
  ProtectedPathRule,
  RegexMatch,
  Rule,
  SkillBinding,
} from "./types.js";

const DEFAULT_CONFIG: GuardrailsConfig = {
  version: 1,
  skillBindings: {},
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

function validateRegex(
  pattern: string,
  flags: string | undefined,
): string | null {
  try {
    void new RegExp(pattern, flags ?? "");
    return null;
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  }
}

function normalizeBlockAction(
  value: unknown,
  path: string,
): BlockAction | string {
  if (!isObject(value)) {
    return `${path} must be an object`;
  }

  const type = value["type"];
  if (type !== "block") {
    return `${path}.type must be "block"`;
  }

  const message = value["message"];
  if (typeof message !== "string" || message.trim().length === 0) {
    return `${path}.message must be a non-empty string`;
  }

  const rawRequiresSkill = value["requiresSkill"];
  if (
    rawRequiresSkill !== undefined &&
    (typeof rawRequiresSkill !== "string" ||
      rawRequiresSkill.trim().length === 0)
  ) {
    return `${path}.requiresSkill must be a non-empty string`;
  }

  const rawRequiredWorkflow = value["requiredWorkflow"];
  if (
    rawRequiredWorkflow !== undefined &&
    (typeof rawRequiredWorkflow !== "string" ||
      rawRequiredWorkflow.trim().length === 0)
  ) {
    return `${path}.requiredWorkflow must be a non-empty string`;
  }

  const rawRequiresBinding = value["requiresBinding"];
  if (
    rawRequiresBinding !== undefined &&
    (typeof rawRequiresBinding !== "string" ||
      rawRequiresBinding.trim().length === 0)
  ) {
    return `${path}.requiresBinding must be a non-empty string`;
  }

  if (
    rawRequiresBinding !== undefined &&
    (rawRequiresSkill !== undefined || rawRequiredWorkflow !== undefined)
  ) {
    return `${path} cannot combine requiresBinding with requiresSkill/requiredWorkflow`;
  }

  const out: BlockAction = {
    type: "block",
    message,
  };
  if (typeof rawRequiresSkill === "string") {
    out.requiresSkill = rawRequiresSkill;
  }
  if (typeof rawRequiredWorkflow === "string") {
    out.requiredWorkflow = rawRequiredWorkflow;
  }
  if (typeof rawRequiresBinding === "string") {
    out.requiresBinding = rawRequiresBinding;
  }
  return out;
}

function normalizeBashAction(
  value: unknown,
  path: string,
): BashAction | string {
  if (!isObject(value)) {
    return `${path} must be an object`;
  }

  const type = value["type"];
  if (type !== "block" && type !== "warn") {
    return `${path}.type must be "block" or "warn"`;
  }

  const message = value["message"];
  if (typeof message !== "string" || message.trim().length === 0) {
    return `${path}.message must be a non-empty string`;
  }

  const rawRequiresSkill = value["requiresSkill"];
  if (
    rawRequiresSkill !== undefined &&
    (typeof rawRequiresSkill !== "string" ||
      rawRequiresSkill.trim().length === 0)
  ) {
    return `${path}.requiresSkill must be a non-empty string`;
  }

  const rawRequiredWorkflow = value["requiredWorkflow"];
  if (
    rawRequiredWorkflow !== undefined &&
    (typeof rawRequiredWorkflow !== "string" ||
      rawRequiredWorkflow.trim().length === 0)
  ) {
    return `${path}.requiredWorkflow must be a non-empty string`;
  }

  const rawRequiresBinding = value["requiresBinding"];
  if (
    rawRequiresBinding !== undefined &&
    (typeof rawRequiresBinding !== "string" ||
      rawRequiresBinding.trim().length === 0)
  ) {
    return `${path}.requiresBinding must be a non-empty string`;
  }

  if (type === "warn" && rawRequiresSkill !== undefined) {
    return `${path}.requiresSkill is only valid for block actions`;
  }
  if (type === "warn" && rawRequiredWorkflow !== undefined) {
    return `${path}.requiredWorkflow is only valid for block actions`;
  }
  if (type === "warn" && rawRequiresBinding !== undefined) {
    return `${path}.requiresBinding is only valid for block actions`;
  }

  if (
    rawRequiresBinding !== undefined &&
    (rawRequiresSkill !== undefined || rawRequiredWorkflow !== undefined)
  ) {
    return `${path} cannot combine requiresBinding with requiresSkill/requiredWorkflow`;
  }

  if (type === "block") {
    const out: BlockAction = {
      type,
      message,
    };
    if (typeof rawRequiresSkill === "string") {
      out.requiresSkill = rawRequiresSkill;
    }
    if (typeof rawRequiredWorkflow === "string") {
      out.requiredWorkflow = rawRequiredWorkflow;
    }
    if (typeof rawRequiresBinding === "string") {
      out.requiresBinding = rawRequiresBinding;
    }
    return out;
  }

  return {
    type,
    message,
  };
}

function normalizeExecutableMatch(
  value: Record<string, unknown>,
  path: string,
): ExecutableMatch | string {
  const rawNames = value["names"];
  const namesValue = rawNames === undefined ? [] : asStringArray(rawNames);
  if (rawNames !== undefined && namesValue === null) {
    return `${path}.names must be an array of strings`;
  }
  const names = namesValue ?? [];

  const rawPatterns = value["patterns"];
  const patternsValue =
    rawPatterns === undefined ? [] : asStringArray(rawPatterns);
  if (rawPatterns !== undefined && patternsValue === null) {
    return `${path}.patterns must be an array of strings`;
  }
  const patterns = patternsValue ?? [];

  if (names.length === 0 && patterns.length === 0) {
    return `${path} must define at least one name or pattern`;
  }

  const rawFlags = value["flags"];
  if (rawFlags !== undefined && typeof rawFlags !== "string") {
    return `${path}.flags must be a string`;
  }
  const flags = typeof rawFlags === "string" ? rawFlags : undefined;

  const rawCaseSensitive = value["caseSensitive"];
  if (rawCaseSensitive !== undefined && typeof rawCaseSensitive !== "boolean") {
    return `${path}.caseSensitive must be a boolean`;
  }
  const caseSensitive =
    typeof rawCaseSensitive === "boolean" ? rawCaseSensitive : undefined;

  for (const [index, pattern] of patterns.entries()) {
    const error = validateRegex(pattern, flags);
    if (error) {
      return `${path}.patterns[${index}] is invalid: ${error}`;
    }
  }

  const out: ExecutableMatch = {
    type: "executable",
    names,
    patterns,
  };
  if (flags !== undefined) {
    out.flags = flags;
  }
  if (caseSensitive !== undefined) {
    out.caseSensitive = caseSensitive;
  }
  return out;
}

function normalizeRegexMatch(
  value: Record<string, unknown>,
  path: string,
): RegexMatch | string {
  const rawPattern = value["pattern"];
  if (typeof rawPattern !== "string" || rawPattern.length === 0) {
    return `${path}.pattern must be a non-empty string`;
  }

  const rawFlags = value["flags"];
  if (rawFlags !== undefined && typeof rawFlags !== "string") {
    return `${path}.flags must be a string`;
  }
  const flags = typeof rawFlags === "string" ? rawFlags : undefined;

  const error = validateRegex(rawPattern, flags);
  if (error) {
    return `${path}.pattern is invalid: ${error}`;
  }

  const out: RegexMatch = {
    type: "regex",
    pattern: rawPattern,
  };
  if (flags !== undefined) {
    out.flags = flags;
  }
  return out;
}

function normalizeMatch(value: unknown, path: string): MatchConfig | string {
  if (!isObject(value)) {
    return `${path} must be an object`;
  }

  const type = value["type"];
  if (type === "executable") {
    return normalizeExecutableMatch(value, path);
  }

  if (type === "regex") {
    return normalizeRegexMatch(value, path);
  }

  return `${path}.type must be "executable" or "regex"`;
}

function normalizeRule(value: unknown, index: number): Rule | string {
  const path = `agentBash.rules[${index}]`;
  if (!isObject(value)) {
    return `${path} must be an object`;
  }

  const rawId = value["id"];
  if (rawId !== undefined && typeof rawId !== "string") {
    return `${path}.id must be a string`;
  }

  const match = normalizeMatch(value["match"], `${path}.match`);
  if (typeof match === "string") {
    return match;
  }

  const action = normalizeBashAction(value["action"], `${path}.action`);
  if (typeof action === "string") {
    return action;
  }

  const out: Rule = {
    match,
    action,
  };
  if (typeof rawId === "string") {
    out.id = rawId;
  }
  return out;
}

function normalizeProtectedPathRule(
  value: unknown,
  index: number,
): ProtectedPathRule | string {
  const path = `protectedPaths.rules[${index}]`;
  if (!isObject(value)) {
    return `${path} must be an object`;
  }

  const rawId = value["id"];
  if (rawId !== undefined && typeof rawId !== "string") {
    return `${path}.id must be a string`;
  }

  const rawPattern = value["pattern"];
  if (typeof rawPattern !== "string" || rawPattern.trim().length === 0) {
    return `${path}.pattern must be a non-empty string`;
  }

  const tools = asStringArray(value["tools"]);
  if (tools === null || tools.length === 0) {
    return `${path}.tools must be a non-empty array of strings`;
  }

  for (const [toolIndex, tool] of tools.entries()) {
    if (tool !== "read" && tool !== "write" && tool !== "edit") {
      return `${path}.tools[${toolIndex}] must be read, write, or edit`;
    }
  }

  const action = normalizeBlockAction(value["action"], `${path}.action`);
  if (typeof action === "string") {
    return action;
  }

  const out: ProtectedPathRule = {
    pattern: rawPattern.trim(),
    tools: tools as Array<"read" | "write" | "edit">,
    action,
  };
  if (typeof rawId === "string") {
    out.id = rawId;
  }
  return out;
}

function normalizeSkillBindings(
  value: unknown,
): Record<string, SkillBinding> | string {
  if (value === undefined) return {};
  if (!isObject(value)) return "skillBindings must be an object";

  const out: Record<string, SkillBinding> = {};
  for (const [name, entry] of Object.entries(value)) {
    if (!isObject(entry)) return `skillBindings.${name} must be an object`;

    const rawRequiresSkill = entry["requiresSkill"];
    if (
      typeof rawRequiresSkill !== "string" ||
      rawRequiresSkill.trim().length === 0
    ) {
      return `skillBindings.${name}.requiresSkill must be a non-empty string`;
    }

    const rawRequiredWorkflow = entry["requiredWorkflow"];
    if (
      rawRequiredWorkflow !== undefined &&
      (typeof rawRequiredWorkflow !== "string" ||
        rawRequiredWorkflow.trim().length === 0)
    ) {
      return `skillBindings.${name}.requiredWorkflow must be a non-empty string`;
    }

    const binding: SkillBinding = {
      requiresSkill: rawRequiresSkill,
    };
    if (typeof rawRequiredWorkflow === "string") {
      binding.requiredWorkflow = rawRequiredWorkflow;
    }
    out[name] = binding;
  }
  return out;
}

function normalizeConfig(value: unknown): GuardrailsConfig | string {
  if (!isObject(value)) {
    return "config root must be an object";
  }

  const version = value["version"];
  if (version !== undefined && version !== 1) {
    return "version must be 1";
  }

  const skillBindings = normalizeSkillBindings(value["skillBindings"]);
  if (typeof skillBindings === "string") {
    return skillBindings;
  }

  const agentBashRaw =
    value["agentBash"] === undefined ? {} : value["agentBash"];
  if (!isObject(agentBashRaw)) {
    return "agentBash must be an object";
  }

  const bashRulesValue =
    agentBashRaw["rules"] === undefined ? [] : agentBashRaw["rules"];
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

  for (const [index, rule] of bashRules.entries()) {
    if (rule.action.type !== "block" || !rule.action.requiresBinding) continue;
    if (!skillBindings[rule.action.requiresBinding]) {
      return `agentBash.rules[${index}].action.requiresBinding references unknown skillBindings key: ${rule.action.requiresBinding}`;
    }
  }

  const protectedPathsRaw =
    value["protectedPaths"] === undefined ? {} : value["protectedPaths"];
  if (!isObject(protectedPathsRaw)) {
    return "protectedPaths must be an object";
  }

  const protectedPathRulesValue =
    protectedPathsRaw["rules"] === undefined ? [] : protectedPathsRaw["rules"];
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
    skillBindings,
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
