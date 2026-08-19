import { Effect, Schema } from "effect";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import type {
  ExtensionAPI,
  ProviderModelConfig,
} from "@earendil-works/pi-coding-agent";
import { piThinkingLevelMap } from "./thinking-levels.ts";

interface CatalogModel {
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
  }) => Promise<readonly CatalogModel[]>;
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
    "sync",
    "src",
    "runtime",
    "model-catalog-client.ts",
  ),
).href;

export const loadCatalogModule = Effect.fn("loadCatalogModule")(function*(): Effect.fn.Return<
  CatalogModule,
  CatalogImportError
> {
  return yield* Effect.tryPromise({
    try: () => import(CATALOG_MODULE) as Promise<CatalogModule>,
    catch: (cause) => new CatalogImportError({ path: CATALOG_MODULE, cause }),
  });
});

export const registerCliProxyProvider = Effect.fn("registerCliProxyProvider")(function*(
  pi: ExtensionAPI,
): Effect.fn.Return<void, CatalogImportError | CatalogResolutionError> {
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

  pi.registerProvider("cliproxy", {
    name: "CLIProxyAPI",
    baseUrl: CLIPROXY_BASE_URL,
    apiKey: "keyless",
    api: "openai-responses",
    models: catalog.map(piModel),
  });
});

export default function cliproxy(pi: ExtensionAPI): Promise<void> {
  return Effect.runPromise(registerCliProxyProvider(pi));
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

function piModel(model: CatalogModel): ProviderModelConfig {
  return {
    id: model.id,
    name: displayName(model.id, model.name),
    reasoning: model.reasoning,
    ...(model.reasoning && model.reasoningEfforts
      ? { thinkingLevelMap: piThinkingLevelMap(model.reasoningEfforts) }
      : {}),
    input: [...model.input],
    cost: { ...model.cost },
    contextWindow: model.contextWindow,
    maxTokens: model.maxTokens,
  };
}
