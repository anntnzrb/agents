import { Effect, Schema } from "effect";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

export interface OpenCodeCatalogModel {
  readonly id: string;
  readonly name: string;
  readonly reasoning: boolean;
  readonly reasoningEfforts?: readonly string[];
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
  readonly resolveLiveModelCatalog: (options: {
    readonly catalogPath: string;
    readonly baseUrl: string;
  }) => Promise<readonly OpenCodeCatalogModel[]>;
}

export class CatalogImportError extends Schema.TaggedError<CatalogImportError>()("CatalogImportError", {
  path: Schema.String,
  cause: Schema.optional(Schema.Unknown),
}) {
  override get message(): string {
    return `import model catalog client ${this.path}`;
  }
}

export class CatalogResolutionError extends Schema.TaggedError<CatalogResolutionError>()(
  "CatalogResolutionError",
  {
    path: Schema.String,
    baseUrl: Schema.String,
    cause: Schema.optional(Schema.Unknown),
  },
) {
  override get message(): string {
    return `resolve live model catalog ${this.baseUrl}`;
  }
}

const CATALOG_PATH = join(
  homedir(),
  ".local",
  "share",
  "agents",
  "model-catalog",
  "catalog.json",
);
const CLIPROXY_BASE_URL = "${CLIPROXY_CLIENT_BASE_URL}";
const CATALOG_MODULE = pathToFileURL(
  join(
    homedir(),
    ".local",
    "share",
    "agents",
    "sync-current",
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

export const loadCatalogModule = Effect.fn("loadCatalogModule")(function*(): Effect.fn.Return<
  CatalogModule,
  CatalogImportError
> {
  return yield* Effect.tryPromise({
    try: () => import(CATALOG_MODULE) as Promise<CatalogModule>,
    catch: (cause) => new CatalogImportError({ path: CATALOG_MODULE, cause }),
  });
});

export const updateOpenCodeConfig = Effect.fn("updateOpenCodeConfig")(function*(
  config: OpenCodeConfig,
): Effect.fn.Return<void, CatalogImportError | CatalogResolutionError> {
  const provider = config.provider?.["cliproxy"];
  if (!provider) {
    return;
  }
  const { resolveLiveModelCatalog } = yield* loadCatalogModule();
  const catalog = yield* Effect.tryPromise({
    try: () =>
      resolveLiveModelCatalog({
        catalogPath: CATALOG_PATH,
        baseUrl: CLIPROXY_BASE_URL,
      }),
    catch: (cause) =>
      new CatalogResolutionError({
        path: CATALOG_PATH,
        baseUrl: CLIPROXY_BASE_URL,
        cause,
      }),
  });
  provider.models = mergeOpenCodeModels(catalog, provider.models ?? {});
});

export const CLIProxyCatalog = async () => ({
  config: (config: OpenCodeConfig) => Effect.runPromise(updateOpenCodeConfig(config)),
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
      ...(model.reasoning && model.reasoningEfforts
        ? { variants: reasoningVariants(model.reasoningEfforts) }
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
  efforts: readonly string[],
): Readonly<Record<string, { readonly reasoningEffort: string }>> {
  const variants = Object.fromEntries(
    efforts.map((effort) => [effort, { reasoningEffort: effort }]),
  );
  const highest = efforts.at(-1);
  return highest ? { ...variants, max: { reasoningEffort: highest } } : variants;
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
