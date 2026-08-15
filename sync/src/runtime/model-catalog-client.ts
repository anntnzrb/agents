import fs from "node:fs";

const CATALOG_VERSION = 1;
const THINKING_LEVELS = ["minimal", "low", "medium", "high", "xhigh", "max"] as const;

type ThinkingLevel = (typeof THINKING_LEVELS)[number];

export interface RuntimeCatalogModel {
  readonly id: string;
  readonly name: string;
  readonly reasoning: boolean;
  readonly thinkingLevelMap?: Readonly<Partial<Record<ThinkingLevel, string | null>>>;
  readonly input: readonly ("text" | "image")[];
  readonly cost: {
    readonly input: number;
    readonly output: number;
    readonly cacheRead: number;
    readonly cacheWrite: number;
  };
  readonly contextWindow: number;
  readonly maxTokens: number;
}

export function readModelCatalog(path: string): readonly RuntimeCatalogModel[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(fs.readFileSync(path, "utf8"));
  } catch (error) {
    throw new Error(`read model catalog ${path}`, { cause: error });
  }
  const root = requireRecord(parsed, "model catalog");
  if (root["version"] !== CATALOG_VERSION || !Array.isArray(root["models"])) {
    throw new Error(`invalid model catalog ${path}`);
  }
  return root["models"].map((value, index) => parseModel(value, `model catalog models[${index}]`));
}

function parseModel(value: unknown, label: string): RuntimeCatalogModel {
  const model = requireRecord(value, label);
  const id = requireString(model["id"], `${label}.id`);
  const name = requireString(model["name"], `${label}.name`);
  if (typeof model["reasoning"] !== "boolean") {
    throw new Error(`invalid ${label}.reasoning`);
  }
  const input = requireInput(model["input"], `${label}.input`);
  const cost = requireRecord(model["cost"], `${label}.cost`);
  const thinkingLevelMap = parseThinkingLevelMap(
    model["thinkingLevelMap"],
    `${label}.thinkingLevelMap`,
  );
  return {
    id,
    name,
    reasoning: model["reasoning"],
    ...(thinkingLevelMap ? { thinkingLevelMap } : {}),
    input,
    cost: {
      input: requireNonNegativeNumber(cost["input"], `${label}.cost.input`),
      output: requireNonNegativeNumber(cost["output"], `${label}.cost.output`),
      cacheRead: requireNonNegativeNumber(cost["cacheRead"], `${label}.cost.cacheRead`),
      cacheWrite: requireNonNegativeNumber(cost["cacheWrite"], `${label}.cost.cacheWrite`),
    },
    contextWindow: requirePositiveInteger(model["contextWindow"], `${label}.contextWindow`),
    maxTokens: requirePositiveInteger(model["maxTokens"], `${label}.maxTokens`),
  };
}

function parseThinkingLevelMap(
  value: unknown,
  label: string,
): RuntimeCatalogModel["thinkingLevelMap"] | undefined {
  if (value === undefined) {
    return undefined;
  }
  const record = requireRecord(value, label);
  const result: Partial<Record<ThinkingLevel, string | null>> = {};
  for (const [level, mapped] of Object.entries(record)) {
    if (!isThinkingLevel(level) || (typeof mapped !== "string" && mapped !== null)) {
      throw new Error(`invalid ${label}.${level}`);
    }
    result[level] = mapped;
  }
  return result;
}

function requireInput(value: unknown, label: string): readonly ("text" | "image")[] {
  if (
    !Array.isArray(value) ||
    value.length === 0 ||
    !value.every((entry) => entry === "text" || entry === "image")
  ) {
    throw new Error(`invalid ${label}`);
  }
  return value;
}

function requireRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`invalid ${label}: expected object`);
  }
  return Object.fromEntries(Object.entries(value));
}

function requireString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`invalid ${label}`);
  }
  return value;
}

function requireNonNegativeNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new Error(`invalid ${label}`);
  }
  return value;
}

function requirePositiveInteger(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`invalid ${label}`);
  }
  return value;
}

function isThinkingLevel(value: string): value is ThinkingLevel {
  return THINKING_LEVELS.some((level) => level === value);
}
