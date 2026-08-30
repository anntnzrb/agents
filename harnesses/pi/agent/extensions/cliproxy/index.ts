import { Effect, Schema } from "effect";
import { homedir } from "node:os";
import { join } from "node:path";
import type {
  ExtensionAPI,
  ProviderModelConfig,
} from "@earendil-works/pi-coding-agent";
import {
  resolveLiveModelCatalog,
  type RuntimeCatalogModel as CatalogModel,
} from "./model-catalog-client.ts";
import { piThinkingLevelMap } from "./thinking-levels.ts";

export type { CatalogModel };

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
  "agentium",
  "model-catalog",
  "catalog.json",
);
const CLIPROXY_BASE_URL = "${CLIPROXY_CLIENT_BASE_URL}";

export const registerCliProxyProvider = Effect.fn("registerCliProxyProvider")(function*(
  pi: ExtensionAPI,
): Effect.fn.Return<void, CatalogResolutionError> {
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
