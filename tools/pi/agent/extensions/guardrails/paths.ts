import type { GuardrailsConfig, ProtectedPathRule } from "./types.js";

const normalizePath = (path: string): string => path.replace(/\\/g, "/");

const getPathSegments = (path: string): string[] =>
  normalizePath(path)
    .split("/")
    .filter((segment) => segment.length > 0);

const matchesProtectedPattern = (path: string, pattern: string): boolean => {
  const normalizedPattern = normalizePath(pattern).replace(/\/$/, "");
  if (normalizedPattern.length === 0) {
    return false;
  }

  if (!normalizedPattern.includes("/")) {
    return getPathSegments(path).includes(normalizedPattern);
  }

  return normalizePath(path).includes(normalizedPattern);
};

const findProtectedPathRule = (
  path: string,
  toolName: "read" | "write" | "edit",
  config: GuardrailsConfig,
): ProtectedPathRule | null => {
  for (const rule of config.protectedPaths.rules) {
    if (!rule.tools.includes(toolName)) {
      continue;
    }
    if (matchesProtectedPattern(path, rule.pattern)) {
      return rule;
    }
  }
  return null;
};

export function reasonForPath(
  path: string,
  toolName: "read" | "write" | "edit",
  config: GuardrailsConfig,
): string | null {
  const rule = findProtectedPathRule(path, toolName, config);
  return rule ? rule.action.message : null;
}
