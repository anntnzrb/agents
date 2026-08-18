import fs from "node:fs";

const CATALOG_VERSION = 1;

export interface RuntimeCatalogModel {
  readonly id: string;
  readonly name: string;
  readonly reasoning: boolean;
  readonly reasoningEfforts?: readonly string[];
  readonly defaultReasoningEffort?: string;
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
  let content: string;
  try {
    content = fs.readFileSync(path, "utf8");
  } catch (error) {
    throw new Error(`read model catalog ${path}`, { cause: error });
  }
  return parseModelCatalog(content, path);
}

export function parseModelCatalog(content: string, path: string): readonly RuntimeCatalogModel[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
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
  const reasoningEfforts =
    parseReasoningEfforts(model["reasoningEfforts"], `${label}.reasoningEfforts`) ??
    parseLegacyThinkingLevelMap(model["thinkingLevelMap"], `${label}.thinkingLevelMap`);
  const defaultReasoningEffort = optionalString(
    model["defaultReasoningEffort"],
    `${label}.defaultReasoningEffort`,
  );
  return {
    id,
    name,
    reasoning: model["reasoning"],
    ...(reasoningEfforts ? { reasoningEfforts } : {}),
    ...(defaultReasoningEffort ? { defaultReasoningEffort } : {}),
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

function parseReasoningEfforts(value: unknown, label: string): readonly string[] | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (!Array.isArray(value) || !value.every((effort) => typeof effort === "string" && effort)) {
    throw new Error(`invalid ${label}`);
  }
  const efforts = [...new Set(value)];
  return efforts.length > 0 ? efforts : undefined;
}

function parseLegacyThinkingLevelMap(value: unknown, label: string): readonly string[] | undefined {
  if (value === undefined) {
    return undefined;
  }
  const record = requireRecord(value, label);
  const efforts: string[] = [];
  for (const [name, mapped] of Object.entries(record)) {
    if (typeof mapped !== "string" && mapped !== null) {
      throw new Error(`invalid ${label}.${name}`);
    }
    if (mapped) {
      efforts.push(mapped);
    }
  }
  return efforts.length > 0 ? [...new Set(efforts)] : undefined;
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

function optionalString(value: unknown, label: string): string | undefined {
  return value === undefined ? undefined : requireString(value, label);
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
