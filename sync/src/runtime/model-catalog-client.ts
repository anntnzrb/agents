import fs from "node:fs";

const CATALOG_VERSION = 1;
const DEFAULT_LIVE_MODELS_TIMEOUT_MS = 2_000;
const TRAILING_SLASH_PATTERN = /\/+$/;
const ZERO_COST = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } as const;

export type LiveModelCatalogFetch = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export interface LiveModelCatalogOptions {
  readonly catalogPath: string;
  readonly baseUrl: string;
  readonly timeoutMs?: number;
  readonly fetch?: LiveModelCatalogFetch;
}

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

export async function resolveLiveModelCatalog(
  options: LiveModelCatalogOptions,
): Promise<readonly RuntimeCatalogModel[]> {
  let local: readonly RuntimeCatalogModel[] | undefined;
  try {
    local = readModelCatalog(options.catalogPath);
  } catch {}

  try {
    return await fetchLiveModelCatalog(options, local ?? []);
  } catch (error) {
    if (local !== undefined) {
      return local;
    }
    throw new Error(`resolve live CLIProxyAPI model catalog ${options.baseUrl}`, {
      cause: error,
    });
  }
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

async function fetchLiveModelCatalog(
  options: LiveModelCatalogOptions,
  local: readonly RuntimeCatalogModel[],
): Promise<readonly RuntimeCatalogModel[]> {
  const response = await (options.fetch ?? globalThis.fetch)(liveModelsUrl(options.baseUrl), {
    headers: { Accept: "application/json", "Cache-Control": "no-cache" },
    cache: "no-store",
    signal: AbortSignal.timeout(options.timeoutMs ?? DEFAULT_LIVE_MODELS_TIMEOUT_MS),
  });
  if (!response.ok) {
    throw new Error(`fetch live CLIProxyAPI models: HTTP ${response.status}`);
  }
  return parseLiveModelCatalog(await response.json(), local);
}

function liveModelsUrl(baseUrl: string): string {
  const url = new URL(baseUrl);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`invalid CLIProxyAPI base URL: ${baseUrl}`);
  }
  url.pathname = `${url.pathname.replace(TRAILING_SLASH_PATTERN, "")}/models`;
  url.search = "?client_version";
  url.hash = "";
  return url.toString();
}

function parseLiveModelCatalog(
  value: unknown,
  local: readonly RuntimeCatalogModel[],
): readonly RuntimeCatalogModel[] {
  const root = requireRecord(value, "live CLIProxyAPI model catalog");
  const rows = root["models"];
  if (!Array.isArray(rows) || rows.length === 0) {
    throw new Error("invalid live CLIProxyAPI model catalog: expected non-empty models array");
  }
  const localById = new Map(local.map((model) => [model.id, model]));
  const models = new Map<string, RuntimeCatalogModel>();
  for (const [index, entry] of rows.entries()) {
    const model = parseLiveModel(
      entry,
      `live CLIProxyAPI model catalog.models[${index}]`,
      localById,
    );
    if (!model) {
      continue;
    }
    if (models.has(model.id)) {
      throw new Error(`duplicate live CLIProxyAPI model id: ${model.id}`);
    }
    models.set(model.id, model);
  }
  if (models.size === 0) {
    throw new Error("live CLIProxyAPI model catalog has no text models");
  }
  return [...models.values()].toSorted((left, right) => compareIds(left.id, right.id));
}

function parseLiveModel(
  value: unknown,
  label: string,
  localById: ReadonlyMap<string, RuntimeCatalogModel>,
): RuntimeCatalogModel | undefined {
  const model = requireRecord(value, label);
  const id = requireString(model["slug"], `${label}.slug`);
  const input = parseLiveInput(model["input_modalities"], `${label}.input_modalities`);
  if (!input.includes("text")) {
    return undefined;
  }
  const reasoningEfforts = parseLiveReasoningEfforts(
    model["supported_reasoning_levels"],
    `${label}.supported_reasoning_levels`,
  );
  const defaultReasoningEffort = optionalString(
    model["default_reasoning_level"],
    `${label}.default_reasoning_level`,
  );
  if (defaultReasoningEffort && !reasoningEfforts.includes(defaultReasoningEffort)) {
    throw new Error(`invalid ${label}.default_reasoning_level`);
  }
  const truncation = requireRecord(model["truncation_policy"], `${label}.truncation_policy`);
  return {
    id,
    name: requireString(model["display_name"], `${label}.display_name`),
    reasoning: reasoningEfforts.some((effort) => effort !== "none"),
    ...(reasoningEfforts.length > 0 ? { reasoningEfforts } : {}),
    ...(defaultReasoningEffort ? { defaultReasoningEffort } : {}),
    input,
    cost: localById.get(id)?.cost ?? { ...ZERO_COST },
    contextWindow: requirePositiveInteger(model["context_window"], `${label}.context_window`),
    maxTokens: requirePositiveInteger(truncation["limit"], `${label}.truncation_policy.limit`),
  };
}

function parseLiveInput(value: unknown, label: string): readonly ("text" | "image")[] {
  if (!Array.isArray(value)) {
    throw new Error(`invalid ${label}`);
  }
  const input: Array<"text" | "image"> = [];
  for (const modality of value) {
    if ((modality === "text" || modality === "image") && !input.includes(modality)) {
      input.push(modality);
    }
  }
  return input;
}

function parseLiveReasoningEfforts(value: unknown, label: string): readonly string[] {
  if (!Array.isArray(value)) {
    throw new Error(`invalid ${label}`);
  }
  const efforts: string[] = [];
  for (const [index, entry] of value.entries()) {
    const level = requireRecord(entry, `${label}[${index}]`);
    const effort = requireString(level["effort"], `${label}[${index}].effort`);
    if (!efforts.includes(effort)) {
      efforts.push(effort);
    }
  }
  return efforts;
}

function compareIds(left: string, right: string): number {
  if (left < right) {
    return -1;
  }
  if (left > right) {
    return 1;
  }
  return 0;
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
