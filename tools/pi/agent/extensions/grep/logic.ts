import path from "node:path";

export const DEFAULT_LIMIT = 100;
export const MAX_LIMIT = 2_000;

export type RawMatch = {
  absolutePath: string;
  displayPath: string;
  lineNumber: number;
  lineText: string;
};

export type TypeFilter = {
  key: string;
  predicate: (absolutePath: string) => boolean;
  rgGlobs: string[];
};

const TYPE_ALIASES: Record<string, string> = {
  typescript: "ts",
  javascript: "js",
  python: "py",
  rust: "rs",
  golang: "go",
};

const TYPE_GLOBS: Record<string, readonly string[]> = {
  ts: ["*.ts", "*.tsx", "*.cts", "*.mts"],
  js: ["*.js", "*.jsx", "*.cjs", "*.mjs"],
  py: ["*.py", "*.pyi"],
  rs: ["*.rs"],
  go: ["*.go"],
  java: ["*.java"],
  kt: ["*.kt", "*.kts"],
  swift: ["*.swift"],
  rb: ["*.rb"],
  php: ["*.php"],
  c: ["*.c", "*.h"],
  cpp: ["*.cc", "*.cpp", "*.cxx", "*.hpp", "*.hh", "*.hxx"],
  cs: ["*.cs"],
  md: ["*.md", "*.markdown"],
  json: ["*.json", "*.jsonc", "*.json5"],
  yaml: ["*.yml", "*.yaml"],
};

const splitCommaPaths = (value: string): string[] =>
  value
    .split(",")
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);

export const normalizeSearchRoots = (singlePath: string | undefined, multiPath: string[] | undefined): string[] => {
  if (singlePath && multiPath && multiPath.length > 0) {
    throw new Error("Use either path or paths, not both");
  }

  const rawEntries: string[] = [];
  if (singlePath?.trim()) {
    rawEntries.push(...splitCommaPaths(singlePath));
  }
  if (multiPath) {
    for (const entry of multiPath) {
      if (typeof entry !== "string") continue;
      rawEntries.push(...splitCommaPaths(entry));
    }
  }

  if (rawEntries.length === 0) return ["."];
  return [...new Set(rawEntries)];
};

export const normalizeLimit = (value: number | undefined): number => {
  const normalized = value === undefined ? DEFAULT_LIMIT : Math.floor(value);
  if (!Number.isFinite(normalized) || normalized <= 0) {
    throw new Error("limit must be a positive number");
  }
  return Math.min(normalized, MAX_LIMIT);
};

export const normalizeOffset = (value: number | undefined): number => {
  const normalized = value === undefined ? 0 : Math.floor(value);
  if (!Number.isFinite(normalized) || normalized < 0) {
    throw new Error("offset must be a non-negative number");
  }
  return normalized;
};

export const resolveTypeFilter = (input: string | undefined): TypeFilter | null => {
  if (!input || input.trim().length === 0) return null;
  const rawKey = input.trim().toLowerCase();
  const key = TYPE_ALIASES[rawKey] ?? rawKey;
  const globs = TYPE_GLOBS[key];
  if (!globs) {
    const supported = Object.keys(TYPE_GLOBS).sort().join(", ");
    throw new Error(`Unknown grep type '${input}'. Supported: ${supported}`);
  }
  const extensions = globs
    .filter((glob) => glob.startsWith("*."))
    .map((glob) => glob.slice(1).toLowerCase());
  const extensionSet = new Set(extensions);
  return {
    key,
    rgGlobs: [...globs],
    predicate: (absolutePath: string) => {
      const lower = absolutePath.toLowerCase();
      for (const ext of extensionSet) {
        if (lower.endsWith(ext)) return true;
      }
      return false;
    },
  };
};

export const balanceMatchesByFile = (matches: RawMatch[]): RawMatch[] => {
  if (matches.length <= 1) return matches;
  const fileOrder: string[] = [];
  const grouped = new Map<string, RawMatch[]>();
  for (const match of matches) {
    if (!grouped.has(match.displayPath)) {
      grouped.set(match.displayPath, []);
      fileOrder.push(match.displayPath);
    }
    grouped.get(match.displayPath)?.push(match);
  }
  if (fileOrder.length <= 1) return matches;

  const indexes = new Map<string, number>(fileOrder.map((file) => [file, 0]));
  const ordered: RawMatch[] = [];
  while (ordered.length < matches.length) {
    let added = false;
    for (const file of fileOrder) {
      const fileMatches = grouped.get(file);
      if (!fileMatches) continue;
      const index = indexes.get(file) ?? 0;
      if (index >= fileMatches.length) continue;
      ordered.push(fileMatches[index]);
      indexes.set(file, index + 1);
      added = true;
    }
    if (!added) break;
  }
  return ordered;
};

export const toPosixRelative = (cwd: string, absolutePath: string): string => {
  const relativeToCwd = path.relative(cwd, absolutePath);
  return relativeToCwd.length === 0 ? path.basename(absolutePath) : relativeToCwd.replace(/\\/g, "/");
};
