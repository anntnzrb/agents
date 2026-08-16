import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

interface CatalogModel {
  readonly id: string;
  readonly name: string;
  readonly reasoning: boolean;
  readonly thinkingLevelMap?: Readonly<Record<string, string | null>>;
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
    apiKey: "!cat ~/.local/share/agents/cliproxyapi/client-api-key",
    api: "openai-responses",
    models,
  });
}

function piModel(model: CatalogModel) {
  return {
    id: model.id,
    name: model.name,
    reasoning: model.reasoning,
    ...(model.thinkingLevelMap ? { thinkingLevelMap: model.thinkingLevelMap } : {}),
    input: [...model.input],
    cost: { ...model.cost },
    contextWindow: model.contextWindow,
    maxTokens: model.maxTokens,
  };
}
