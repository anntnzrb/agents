export { normalizeSearchRoots } from "../_shared/search-input.js";

export const DEFAULT_LIMIT = 1_000;
export const MAX_LIMIT = 10_000;
export const DEFAULT_TIMEOUT_MS = 5_000;

export const normalizeLimit = (value: number | undefined): number => {
  const normalized = value === undefined ? DEFAULT_LIMIT : Math.floor(value);
  if (!Number.isFinite(normalized) || normalized <= 0) {
    throw new Error("limit must be a positive number");
  }
  return Math.min(normalized, MAX_LIMIT);
};

export const normalizeTimeout = (value: number | undefined): number => {
  const normalized = value === undefined ? DEFAULT_TIMEOUT_MS : Math.floor(value);
  if (!Number.isFinite(normalized) || normalized <= 0) {
    throw new Error("timeoutMs must be a positive number");
  }
  return normalized;
};

export const buildFdArgs = (pattern: string, rootAbsolute: string, includeHidden: boolean, limit: number): string[] => {
  const args = ["--glob", "--color=never", "--no-require-git", "--max-results", String(limit)];
  if (includeHidden) args.push("--hidden");

  let effectivePattern = pattern;
  if (pattern.includes("/")) {
    args.push("--full-path");
    if (!pattern.startsWith("/") && !pattern.startsWith("**/") && pattern !== "**") {
      effectivePattern = `**/${pattern}`;
    }
  }
  args.push(effectivePattern, rootAbsolute);
  return args;
};
