import fs from "node:fs";
import { syncTextFile } from "./secret-template.ts";

export type CatalogApi = "anthropic-messages" | "openai-completions" | "openai-responses";

export interface ModelCatalogSource {
  readonly id: string;
  readonly modelsDevProvider: string;
  readonly prefix: string;
  readonly baseUrl: string;
}

export interface CatalogCost {
  readonly input: number;
  readonly output: number;
  readonly cacheRead: number;
  readonly cacheWrite: number;
}

export interface CatalogModel {
  readonly id: string;
  readonly name: string;
  readonly api: CatalogApi;
  readonly reasoning: boolean;
  readonly reasoningEfforts?: readonly string[];
  readonly defaultReasoningEffort?: string;
  readonly input: readonly ("text" | "image")[];
  readonly cost: CatalogCost;
  readonly contextWindow: number;
  readonly maxTokens: number;
  readonly compat?: Readonly<Record<string, unknown>>;
}

export interface CliProxyModelMapping {
  readonly name: string;
  readonly alias: string;
  readonly "display-name": string;
  readonly "max-context-length": number;
  readonly "force-mapping": true;
  readonly "is-compat": true;
  readonly thinking?: {
    readonly levels: readonly string[];
  };
}

export interface UnsupportedCatalogModel {
  readonly id: string;
  readonly npm: string | undefined;
  readonly shape: string | undefined;
}

export interface SourceModels {
  readonly groups: ReadonlyMap<CatalogApi, readonly CliProxyModelMapping[]>;
  readonly models: readonly CatalogModel[];
  readonly unsupported: readonly UnsupportedCatalogModel[];
}

export interface CatalogAlias {
  readonly id: string;
  readonly sourceId: string;
  readonly name?: string;
}

export interface GatewayCatalogOptions {
  readonly aliases?: readonly CatalogAlias[];
  readonly modelsDev?: unknown;
  readonly managedPrefixes?: readonly string[];
  readonly richGatewayPayload?: unknown;
}

const ZERO_COST: CatalogCost = {
  input: 0,
  output: 0,
  cacheRead: 0,
  cacheWrite: 0,
};
const compareIds = (left: string, right: string): number => {
  if (left < right) {
    return -1;
  }
  if (left > right) {
    return 1;
  }
  return 0;
};
const MODEL_CATALOG_VERSION = 1;
const MODEL_CATALOG_MODE = 0o600;

const GENERATION_ONLY_MODEL_PATTERNS = [
  /^codex-auto-review$/i,
  /^gpt-image-/i,
  /^grok-imagine-/i,
  /(?:^|-)image(?:-|$)/i,
  /(?:^|-)video(?:-|$)/i,
] as const;

export function modelsForSource(
  source: ModelCatalogSource,
  upstreamPayload: unknown,
  modelsDevPayload: unknown,
): SourceModels {
  validateSource(source);
  const upstreamRows = openAIDataRows(upstreamPayload, `${source.id} model catalog`);
  const modelsDev = expectRecord(modelsDevPayload, "models.dev catalog");
  const provider = expectRecord(
    modelsDev[source.modelsDevProvider],
    `models.dev provider ${source.modelsDevProvider}`,
  );
  const providerNpm = stringField(provider, "npm");
  if (!providerNpm) {
    throw new Error(`invalid models.dev provider ${source.modelsDevProvider}: missing npm`);
  }
  const metadataById = optionalRecord(provider["models"]) ?? {};
  const entries: Array<{
    readonly mapping: CliProxyModelMapping;
    readonly model: CatalogModel;
  }> = [];
  const unsupported: UnsupportedCatalogModel[] = [];

  for (const upstream of upstreamRows) {
    const id = stringField(upstream, "id");
    if (!id || GENERATION_ONLY_MODEL_PATTERNS.some((pattern) => pattern.test(id))) {
      continue;
    }
    const metadata = optionalRecord(metadataById[id]);
    if (!isAgentModel(metadata, upstream)) {
      continue;
    }
    const modelProvider = optionalRecord(metadata?.["provider"]);
    const npm = stringField(modelProvider, "npm") ?? providerNpm;
    const shape = stringField(modelProvider, "shape");
    const api = apiForProvider(npm, shape);
    if (!api) {
      unsupported.push({ id, npm, shape });
      continue;
    }
    const alias = publicAlias(source, id);
    const model = normalizeModel(source, alias, api, metadata, upstream);
    entries.push({
      mapping: mappingFor(id, alias, model),
      model,
    });
  }

  const sorted = entries.toSorted((left, right) => compareIds(left.model.id, right.model.id));
  const groups = new Map<CatalogApi, CliProxyModelMapping[]>();
  for (const entry of sorted) {
    const group = groups.get(entry.model.api) ?? [];
    group.push(entry.mapping);
    groups.set(entry.model.api, group);
  }
  return {
    groups: new Map([...groups.entries()].toSorted(([left], [right]) => compareIds(left, right))),
    models: sorted.map((entry) => entry.model),
    unsupported: unsupported.toSorted((left, right) => compareIds(left.id, right.id)),
  };
}

export function enrichGatewayModels(
  discovered: readonly CatalogModel[],
  gatewayPayload: unknown,
  options: GatewayCatalogOptions = {},
): CatalogModel[] {
  const richModels = richGatewayModels(options.richGatewayPayload);
  const byId = new Map(
    discovered.map((model) => [
      model.id,
      enrichWithRichGatewayModel(model, richModels.get(model.id)),
    ]),
  );
  const managedPrefixes = new Set(options.managedPrefixes ?? []);
  const gatewayIds = new Set<string>();
  for (const row of openAIDataRows(gatewayPayload, "CLIProxyAPI model catalog")) {
    const id = stringField(row, "id");
    const ownedBy = stringField(row, "owned_by");
    if (!id || !ownedBy || GENERATION_ONLY_MODEL_PATTERNS.some((pattern) => pattern.test(id))) {
      continue;
    }
    gatewayIds.add(id);
    if (managedPrefixes.has(id.split("/", 1)[0] ?? "") || byId.has(id)) {
      continue;
    }
    byId.set(
      id,
      enrichWithRichGatewayModel(
        gatewayModel(id, ownedBy, row, options.modelsDev),
        richModels.get(id),
      ),
    );
  }
  for (const alias of options.aliases ?? []) {
    if (byId.has(alias.id) || (!gatewayIds.has(alias.id) && !richModels.has(alias.id))) {
      continue;
    }
    const source = byId.get(alias.sourceId);
    if (!source) {
      continue;
    }
    byId.set(
      alias.id,
      enrichWithRichGatewayModel(
        { ...source, id: alias.id, ...(alias.name ? { name: alias.name } : {}) },
        richModels.get(alias.id),
      ),
    );
  }
  return [...byId.values()].toSorted((left, right) => compareIds(left.id, right.id));
}

export function writeModelCatalog(path: string, models: readonly CatalogModel[]): void {
  const unique = new Map<string, CatalogModel>();
  for (const model of models) {
    if (unique.has(model.id)) {
      throw new Error(`duplicate model catalog id: ${model.id}`);
    }
    unique.set(model.id, model);
  }
  syncTextFile(
    path,
    `${JSON.stringify(
      {
        version: MODEL_CATALOG_VERSION,
        models: [...unique.values()].toSorted((left, right) => compareIds(left.id, right.id)),
      },
      null,
      2,
    )}\n`,
    MODEL_CATALOG_MODE,
  );
}

export function readModelCatalog(path: string): readonly CatalogModel[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(fs.readFileSync(path, "utf8"));
  } catch (error) {
    throw new Error(`read model catalog ${path}`, { cause: error });
  }
  const root = expectRecord(parsed, "model catalog");
  if (root["version"] !== MODEL_CATALOG_VERSION || !Array.isArray(root["models"])) {
    throw new Error(`invalid model catalog ${path}`);
  }
  return root["models"].map((value, index) =>
    parseCatalogModel(value, `model catalog models[${index}]`),
  );
}

function normalizeModel(
  source: ModelCatalogSource,
  alias: string,
  api: CatalogApi,
  metadata: Record<string, unknown> | undefined,
  upstream: Record<string, unknown>,
): CatalogModel {
  const limit = optionalRecord(metadata?.["limit"]);
  const contextWindow =
    positiveInteger(upstream["context_length"]) ?? positiveInteger(limit?.["context"]) ?? 128000;
  const topProvider = optionalRecord(upstream["top_provider"]);
  const maxTokens =
    positiveInteger(upstream["max_completion_tokens"]) ??
    positiveInteger(topProvider?.["max_completion_tokens"]) ??
    positiveInteger(limit?.["output"]) ??
    Math.min(contextWindow, 16384);
  const architecture = optionalRecord(upstream["architecture"]);
  const modalities = optionalRecord(metadata?.["modalities"]);
  const inputModalities = [
    ...stringArray(architecture?.["input_modalities"]),
    ...stringArray(modalities?.["input"]),
  ];
  const pricing = optionalRecord(upstream["pricing"]);
  const metadataCost = optionalRecord(metadata?.["cost"]);
  const efforts = reasoningEfforts(metadata?.["reasoning_options"]);
  const defaultReasoningEffort = stringField(metadata, "default_reasoning_effort");
  const supportedParameters = stringArray(upstream["supported_parameters"]);
  return {
    id: `${source.prefix}/${alias}`,
    name: stringField(upstream, "name") ?? stringField(metadata, "name") ?? alias,
    api,
    reasoning:
      metadata?.["reasoning"] === true ||
      efforts?.some((effort) => effort !== "none") === true ||
      supportedParameters.includes("reasoning") ||
      supportedParameters.includes("reasoning_effort"),
    ...(efforts ? { reasoningEfforts: efforts } : {}),
    ...(defaultReasoningEffort ? { defaultReasoningEffort } : {}),
    input: inputModalities.includes("image") ? ["text", "image"] : ["text"],
    cost: {
      input:
        perTokenPriceToMillions(pricing?.["prompt"]) ?? nonNegativeNumber(metadataCost?.["input"]),
      output:
        perTokenPriceToMillions(pricing?.["completion"]) ??
        nonNegativeNumber(metadataCost?.["output"]),
      cacheRead:
        perTokenPriceToMillions(pricing?.["input_cache_read"]) ??
        nonNegativeNumber(metadataCost?.["cache_read"]),
      cacheWrite:
        perTokenPriceToMillions(pricing?.["input_cache_write"]) ??
        nonNegativeNumber(metadataCost?.["cache_write"]),
    },
    contextWindow,
    maxTokens,
    ...compatFor(metadata, supportedParameters),
  };
}

function apiForProvider(npm: string, shape: string | undefined): CatalogApi | undefined {
  if (shape === "responses") {
    return "openai-responses";
  }
  if (shape === "completions") {
    return "openai-completions";
  }
  if (npm === "@ai-sdk/openai" || npm === "@ai-sdk/azure") {
    return "openai-responses";
  }
  if (npm === "@ai-sdk/anthropic") {
    return "anthropic-messages";
  }
  if (npm === "@ai-sdk/openai-compatible") {
    return "openai-completions";
  }
  return undefined;
}

function isAgentModel(
  metadata: Record<string, unknown> | undefined,
  upstream: Record<string, unknown>,
): boolean {
  if (metadata?.["tool_call"] === false) {
    return false;
  }
  const metadataModalities = optionalRecord(metadata?.["modalities"]);
  const metadataOutput = stringArray(metadataModalities?.["output"]);
  if (metadataOutput.length > 0 && !metadataOutput.includes("text")) {
    return false;
  }
  const architecture = optionalRecord(upstream["architecture"]);
  const upstreamOutput = stringArray(architecture?.["output_modalities"]);
  if (upstreamOutput.length > 0 && !upstreamOutput.includes("text")) {
    return false;
  }
  const supportedParameters = stringArray(upstream["supported_parameters"]);
  return supportedParameters.length === 0 || supportedParameters.includes("tools");
}

function mappingFor(upstreamId: string, alias: string, model: CatalogModel): CliProxyModelMapping {
  return {
    name: upstreamId,
    alias,
    "display-name": model.name,
    "max-context-length": model.contextWindow,
    "force-mapping": true,
    "is-compat": true,
    ...(model.reasoningEfforts && model.reasoningEfforts.length > 0
      ? { thinking: { levels: model.reasoningEfforts } }
      : {}),
  };
}

function gatewayModel(
  id: string,
  ownedBy: string,
  gateway: Record<string, unknown>,
  modelsDevPayload: unknown,
): CatalogModel {
  const reference = findModelsDevReference(modelsDevPayload, ownedBy, unprefixedModelId(id));
  const metadata = reference?.model;
  const modelProvider = optionalRecord(metadata?.["provider"]);
  const npm =
    stringField(modelProvider, "npm") ?? reference?.providerNpm ?? "@ai-sdk/openai-compatible";
  const api = apiForProvider(npm, stringField(modelProvider, "shape")) ?? "openai-completions";
  const limit = optionalRecord(metadata?.["limit"]);
  const contextWindow =
    positiveInteger(gateway["context_length"]) ?? positiveInteger(limit?.["context"]) ?? 128000;
  const maxTokens =
    positiveInteger(gateway["max_completion_tokens"]) ??
    positiveInteger(limit?.["output"]) ??
    Math.min(contextWindow, 16384);
  const modalities = optionalRecord(metadata?.["modalities"]);
  const cost = optionalRecord(metadata?.["cost"]);
  const efforts = reasoningEfforts(metadata?.["reasoning_options"]);
  const defaultReasoningEffort = stringField(metadata, "default_reasoning_effort");
  const supportedParameters = stringArray(gateway["supported_parameters"]);
  return {
    id,
    name: stringField(metadata, "name") ?? id,
    api,
    reasoning:
      metadata?.["reasoning"] === true ||
      efforts?.some((effort) => effort !== "none") === true ||
      supportedParameters.includes("reasoning") ||
      supportedParameters.includes("reasoning_effort"),
    ...(efforts ? { reasoningEfforts: efforts } : {}),
    ...(defaultReasoningEffort ? { defaultReasoningEffort } : {}),
    input: stringArray(modalities?.["input"]).includes("image") ? ["text", "image"] : ["text"],
    cost: cost
      ? {
          input: nonNegativeNumber(cost["input"]),
          output: nonNegativeNumber(cost["output"]),
          cacheRead: nonNegativeNumber(cost["cache_read"]),
          cacheWrite: nonNegativeNumber(cost["cache_write"]),
        }
      : ZERO_COST,
    contextWindow,
    maxTokens,
    ...compatFor(metadata, supportedParameters),
  };
}

interface RichGatewayModel {
  readonly name?: string;
  readonly contextWindow?: number;
  readonly input?: readonly ("text" | "image")[];
  readonly reasoningEfforts?: readonly string[];
  readonly defaultReasoningEffort?: string;
}

function richGatewayModels(payload: unknown): ReadonlyMap<string, RichGatewayModel> {
  if (payload === undefined) {
    return new Map();
  }
  const root = expectRecord(payload, "CLIProxyAPI rich model catalog");
  if (!Array.isArray(root["models"])) {
    throw new Error("invalid CLIProxyAPI rich model catalog: expected models array");
  }
  const models = new Map<string, RichGatewayModel>();
  for (const [index, value] of root["models"].entries()) {
    const row = expectRecord(value, `CLIProxyAPI rich model catalog.models[${index}]`);
    const id = stringField(row, "slug");
    if (!id) {
      throw new Error(`invalid CLIProxyAPI rich model catalog.models[${index}].slug`);
    }
    const input = stringArray(row["input_modalities"]).filter(
      (entry): entry is "text" | "image" => entry === "text" || entry === "image",
    );
    const name = stringField(row, "display_name");
    const contextWindow = positiveInteger(row["context_window"]);
    const defaultReasoningEffort = stringField(row, "default_reasoning_level");
    models.set(id, {
      ...(name ? { name } : {}),
      ...(contextWindow ? { contextWindow } : {}),
      ...(input.length > 0 ? { input } : {}),
      ...(row["supported_reasoning_levels"] === undefined
        ? {}
        : { reasoningEfforts: richReasoningEfforts(row["supported_reasoning_levels"], index) }),
      ...(defaultReasoningEffort ? { defaultReasoningEffort } : {}),
    });
  }
  return models;
}

function richReasoningEfforts(value: unknown, modelIndex: number): readonly string[] {
  if (!Array.isArray(value)) {
    throw new Error(
      `invalid CLIProxyAPI rich model catalog.models[${modelIndex}].supported_reasoning_levels`,
    );
  }
  return orderedUnique(
    value.flatMap((entry, levelIndex) => {
      const level = expectRecord(
        entry,
        `CLIProxyAPI rich model catalog.models[${modelIndex}].supported_reasoning_levels[${levelIndex}]`,
      );
      const effort = stringField(level, "effort");
      return effort ? [effort] : [];
    }),
  );
}

function enrichWithRichGatewayModel(
  model: CatalogModel,
  rich: RichGatewayModel | undefined,
): CatalogModel {
  if (!rich) {
    return model;
  }
  const efforts =
    rich.reasoningEfforts === undefined
      ? model.reasoningEfforts
      : rich.reasoningEfforts.length > 0
        ? rich.reasoningEfforts
        : undefined;
  const { reasoningEfforts: _oldReasoningEfforts, ...base } = model;
  return {
    ...base,
    ...(rich.name ? { name: rich.name } : {}),
    reasoning:
      rich.reasoningEfforts !== undefined
        ? rich.reasoningEfforts.some((effort) => effort !== "none")
        : model.reasoning,
    ...(efforts ? { reasoningEfforts: efforts } : {}),
    ...(rich.defaultReasoningEffort ? { defaultReasoningEffort: rich.defaultReasoningEffort } : {}),
    ...(rich.input ? { input: rich.input } : {}),
    ...(rich.contextWindow ? { contextWindow: rich.contextWindow } : {}),
  };
}

interface ModelsDevReference {
  readonly providerNpm: string;
  readonly model: Record<string, unknown>;
}

function findModelsDevReference(
  payload: unknown,
  ownedBy: string,
  modelId: string,
): ModelsDevReference | undefined {
  const providers = optionalRecord(payload);
  if (!providers) {
    return undefined;
  }
  const preferred = modelsDevReferenceFromProvider(providers[ownedBy], modelId);
  if (preferred) {
    return preferred;
  }
  for (const providerId of Object.keys(providers).toSorted()) {
    const reference = modelsDevReferenceFromProvider(providers[providerId], modelId);
    if (reference) {
      return reference;
    }
  }
  return undefined;
}

function parseCatalogModel(value: unknown, label: string): CatalogModel {
  const model = expectRecord(value, label);
  const api = model["api"];
  if (api !== "anthropic-messages" && api !== "openai-completions" && api !== "openai-responses") {
    throw new Error(`invalid ${label}.api`);
  }
  const id = stringField(model, "id");
  const name = stringField(model, "name");
  const input = stringArray(model["input"]).filter(
    (entry): entry is "text" | "image" => entry === "text" || entry === "image",
  );
  const cost = expectRecord(model["cost"], `${label}.cost`);
  const contextWindow = positiveInteger(model["contextWindow"]);
  const maxTokens = positiveInteger(model["maxTokens"]);
  const efforts =
    parseReasoningEfforts(model["reasoningEfforts"], `${label}.reasoningEfforts`) ??
    parseLegacyThinkingLevelMap(model["thinkingLevelMap"], `${label}.thinkingLevelMap`);
  const defaultReasoningEffort = stringField(model, "defaultReasoningEffort");
  const compat = optionalRecord(model["compat"]);
  if (
    !id ||
    !name ||
    typeof model["reasoning"] !== "boolean" ||
    input.length === 0 ||
    !contextWindow ||
    !maxTokens
  ) {
    throw new Error(`invalid ${label}`);
  }
  return {
    id,
    name,
    api,
    reasoning: model["reasoning"],
    ...(efforts ? { reasoningEfforts: efforts } : {}),
    ...(defaultReasoningEffort ? { defaultReasoningEffort } : {}),
    input,
    cost: {
      input: nonNegativeNumber(cost["input"]),
      output: nonNegativeNumber(cost["output"]),
      cacheRead: nonNegativeNumber(cost["cacheRead"]),
      cacheWrite: nonNegativeNumber(cost["cacheWrite"]),
    },
    contextWindow,
    maxTokens,
    ...(compat ? { compat } : {}),
  };
}

function parseReasoningEfforts(value: unknown, label: string): readonly string[] | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (!Array.isArray(value) || !value.every((effort) => typeof effort === "string" && effort)) {
    throw new Error(`invalid ${label}`);
  }
  const efforts = orderedUnique(value);
  return efforts.length > 0 ? efforts : undefined;
}

function parseLegacyThinkingLevelMap(value: unknown, label: string): readonly string[] | undefined {
  if (value === undefined) {
    return undefined;
  }
  const record = expectRecord(value, label);
  const efforts: string[] = [];
  for (const [name, mapped] of Object.entries(record)) {
    if (typeof mapped !== "string" && mapped !== null) {
      throw new Error(`invalid ${label}.${name}`);
    }
    if (mapped) {
      efforts.push(mapped);
    }
  }
  return efforts.length > 0 ? orderedUnique(efforts) : undefined;
}

function modelsDevReferenceFromProvider(
  value: unknown,
  modelId: string,
): ModelsDevReference | undefined {
  const provider = optionalRecord(value);
  const providerNpm = stringField(provider, "npm");
  const models = optionalRecord(provider?.["models"]);
  const model = optionalRecord(models?.[modelId]);
  return providerNpm && model ? { providerNpm, model } : undefined;
}

function publicAlias(source: ModelCatalogSource, id: string): string {
  const repeatedPrefix = `${source.prefix}/`;
  return id.startsWith(repeatedPrefix) ? id.slice(repeatedPrefix.length) : id;
}

function unprefixedModelId(id: string): string {
  const slash = id.indexOf("/");
  return slash > 0 ? id.slice(slash + 1) : id;
}

function compatFor(
  metadata: Record<string, unknown> | undefined,
  supportedParameters: readonly string[],
): { readonly compat: Readonly<Record<string, unknown>> } | undefined {
  const interleaved = optionalRecord(metadata?.["interleaved"]);
  const reasoningField = stringField(interleaved, "field");
  if (reasoningField === "reasoning_details") {
    return {
      compat: {
        thinkingFormat: "openrouter",
        ...(supportedParameters.includes("tool_choice") ? {} : { supportsToolChoice: false }),
      },
    };
  }
  if (reasoningField === "reasoning_content") {
    return {
      compat: {
        thinkingFormat: "deepseek",
        requiresReasoningContentOnAssistantMessages: true,
      },
    };
  }
  if (supportedParameters.length > 0 && !supportedParameters.includes("tool_choice")) {
    return { compat: { supportsToolChoice: false } };
  }
  return undefined;
}

function reasoningEfforts(value: unknown): readonly string[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const effort = value.map(optionalRecord).find((option) => option?.["type"] === "effort");
  if (!Array.isArray(effort?.["values"])) {
    return undefined;
  }
  const efforts = orderedUnique(
    effort["values"].flatMap((raw) =>
      raw === null ? ["none"] : typeof raw === "string" && raw ? [raw] : [],
    ),
  );
  return efforts.length > 0 ? efforts : undefined;
}

function orderedUnique(values: readonly string[]): string[] {
  return [...new Set(values)];
}

export function openAIDataRows(payload: unknown, label: string): Record<string, unknown>[] {
  const root = expectRecord(payload, label);
  if (!Array.isArray(root["data"])) {
    throw new Error(`invalid ${label}: expected data array`);
  }
  return root["data"].map((value, index) => expectRecord(value, `${label}.data[${index}]`));
}

function perTokenPriceToMillions(value: unknown): number | undefined {
  if (typeof value !== "string" && typeof value !== "number") {
    return undefined;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed * 1_000_000 : undefined;
}

function nonNegativeNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
}

function positiveInteger(value: unknown): number | undefined {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : undefined;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((entry): entry is string => typeof entry === "string")
    : [];
}

function stringField(value: Record<string, unknown> | undefined, name: string): string | undefined {
  const field = value?.[name];
  return typeof field === "string" && field.length > 0 ? field : undefined;
}

function validateSource(source: ModelCatalogSource): void {
  for (const [name, value] of Object.entries(source)) {
    if (typeof value !== "string" || value.length === 0) {
      throw new Error(`invalid model catalog source ${source.id}.${name}`);
    }
  }
  if (source.prefix.includes("/")) {
    throw new Error(`invalid model catalog prefix: ${source.prefix}`);
  }
  const url = new URL(source.baseUrl);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`invalid model catalog base URL: ${source.baseUrl}`);
  }
}

function expectRecord(value: unknown, label: string): Record<string, unknown> {
  const record = optionalRecord(value);
  if (!record) {
    throw new Error(`invalid ${label}: expected object`);
  }
  return record;
}

function optionalRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? Object.fromEntries(Object.entries(value))
    : undefined;
}
