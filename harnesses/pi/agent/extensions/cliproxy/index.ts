import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
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

export default async function cliproxy(pi: ExtensionAPI): Promise<void> {
  const { readModelCatalog } = (await import(CATALOG_MODULE)) as CatalogModule;
  const models = readModelCatalog(CATALOG_PATH).map(piModel);

  pi.registerProvider("cliproxy", {
    name: "CLIProxyAPI",
    baseUrl: "${CLIPROXY_CLIENT_BASE_URL}",
    apiKey: "keyless",
    api: "openai-responses",
    models,
  });
}

function piModel(model: CatalogModel) {
  return {
    id: model.id,
    name: model.name,
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
