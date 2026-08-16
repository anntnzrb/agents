import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

interface CatalogModel {
  readonly id: string;
  readonly name: string;
  readonly reasoning: boolean;
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
  readonly readModelCatalog: (path: string) => readonly CatalogModel[];
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
    provider.models = Object.fromEntries(readModelCatalog(CATALOG_PATH).map(openCodeModel));
  },
});

function openCodeModel(model: CatalogModel): readonly [string, unknown] {
  return [
    model.id,
    {
      name: displayName(model.id, model.name),
      reasoning: model.reasoning,
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
