import { Effect, Schema } from "effect";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { readFile } from "node:fs/promises";
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
  readonly parseModelCatalog: (content: string, path: string) => readonly CatalogModel[];
}

export class CatalogReadError extends Schema.TaggedError<CatalogReadError>()("CatalogReadError", {
  path: Schema.String,
  cause: Schema.optional(Schema.Unknown),
}) {
  override get message(): string {
    return `read model catalog ${this.path}`;
  }
}

export class CatalogImportError extends Schema.TaggedError<CatalogImportError>()("CatalogImportError", {
  path: Schema.String,
  cause: Schema.optional(Schema.Unknown),
}) {
  override get message(): string {
    return `import model catalog client ${this.path}`;
  }
}

export class CatalogParseError extends Schema.TaggedError<CatalogParseError>()("CatalogParseError", {
  path: Schema.String,
  cause: Schema.optional(Schema.Unknown),
}) {
  override get message(): string {
    return `parse model catalog ${this.path}`;
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

export const readCatalogContent = Effect.fn("readCatalogContent")(function*(
  path: string,
): Effect.fn.Return<string, CatalogReadError> {
  return yield* Effect.tryPromise({
    try: () => readFile(path, "utf8"),
    catch: (cause) => new CatalogReadError({ path, cause }),
  });
});

export const registerCliProxyProvider = Effect.fn("registerCliProxyProvider")(function*(
  pi: ExtensionAPI,
): Effect.fn.Return<void, CatalogImportError | CatalogReadError | CatalogParseError> {
  const { parseModelCatalog } = yield* loadCatalogModule();
  const content = yield* readCatalogContent(CATALOG_PATH);
  const catalog = yield* Effect.try({
    try: () => parseModelCatalog(content, CATALOG_PATH),
    catch: (cause) => new CatalogParseError({ path: CATALOG_PATH, cause }),
  });
  const models = catalog.map(piModel);

  pi.registerProvider("cliproxy", {
    name: "CLIProxyAPI",
    baseUrl: "${CLIPROXY_CLIENT_BASE_URL}",
    apiKey: "keyless",
    api: "openai-responses",
    models,
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
