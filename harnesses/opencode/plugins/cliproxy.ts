import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const THINKING_LEVELS = ["minimal", "low", "medium", "high", "xhigh", "max"] as const;
type ThinkingLevel = (typeof THINKING_LEVELS)[number];

export interface OpenCodeCatalogModel {
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

interface CatalogModule {
  readonly readModelCatalog: (path: string) => readonly OpenCodeCatalogModel[];
}

const CATALOG_PATH = join(
  homedir(),
  ".local",
  "share",
  "agents",
  "model-catalog",
  "catalog.json",
);
const CATALOG_MODULE = pathToFileURL(
  join(
    homedir(),
    ".local",
    "share",
    "agents",
    "sync",
    "src",
    "runtime",
    "model-catalog-client.ts",
  ),
).href;

interface OpenCodeConfig {
  provider?: Record<string, { models?: Record<string, unknown> }>;
}

function displayName(id: string, catalogName: string): string {
  const slash = id.indexOf("/");
  if (slash <= 0) {
    return catalogName || id;
  }
  const prefix = id.slice(0, slash);
  const model = id.slice(slash + 1);
  const title = catalogName && catalogName !== id ? catalogName : model;
  return `${prefix} — ${title}`;
}

export const CLIProxyCatalog = async () => ({
  config: async (config: OpenCodeConfig) => {
    const provider = config.provider?.["cliproxy"];
    if (!provider) {
      return;
    }
    const { readModelCatalog } = (await import(CATALOG_MODULE)) as CatalogModule;
    provider.models = mergeOpenCodeModels(readModelCatalog(CATALOG_PATH), provider.models ?? {});
  },
});

export function mergeOpenCodeModels(
  catalog: readonly OpenCodeCatalogModel[],
  configured: Readonly<Record<string, unknown>>,
): Record<string, unknown> {
  const generated = Object.fromEntries(catalog.map(openCodeModel));
  const models: Record<string, unknown> = { ...generated };
  for (const [id, value] of Object.entries(configured)) {
    const configuredModel = record(value);
    const generatedModel = record(generated[id]);
    if (!configuredModel || !generatedModel) {
      models[id] = value;
      continue;
    }
    models[id] = {
      ...generatedModel,
      ...configuredModel,
      ...mergeField(generatedModel, configuredModel, "options"),
      ...mergeField(generatedModel, configuredModel, "variants"),
    };
  }
  return models;
}

function openCodeModel(model: OpenCodeCatalogModel): readonly [string, unknown] {
  return [
    model.id,
    {
      name: displayName(model.id, model.name),
      reasoning: model.reasoning,
      ...(model.thinkingLevelMap
        ? { variants: reasoningVariants(model.thinkingLevelMap) }
        : {}),
      tool_call: true,
      modalities: { input: model.input, output: ["text"] },
      cost: {
        input: model.cost.input,
        output: model.cost.output,
        cache_read: model.cost.cacheRead,
        cache_write: model.cost.cacheWrite,
      },
      limit: { context: model.contextWindow, output: model.maxTokens },
    },
  ];
}

function reasoningVariants(
  levelMap: NonNullable<OpenCodeCatalogModel["thinkingLevelMap"]>,
): Readonly<Record<ThinkingLevel, { readonly reasoningEffort: string }>> {
  const supported = THINKING_LEVELS.flatMap((level, index) =>
    typeof levelMap[level] === "string" ? [{ level, index, effort: levelMap[level] }] : [],
  );
  return Object.fromEntries(
    THINKING_LEVELS.flatMap((requested, requestedIndex) => {
      const selected =
        supported.findLast(({ index }) => index <= requestedIndex) ?? supported.at(0);
      return selected ? [[requested, { reasoningEffort: selected.effort }]] : [];
    }),
  ) as Record<ThinkingLevel, { readonly reasoningEffort: string }>;
}

function mergeField(
  generated: Record<string, unknown>,
  configured: Record<string, unknown>,
  field: "options" | "variants",
): Record<string, unknown> {
  const left = record(generated[field]);
  const right = record(configured[field]);
  return left || right ? { [field]: { ...left, ...right } } : {};
}

function record(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? Object.fromEntries(Object.entries(value))
    : undefined;
}
