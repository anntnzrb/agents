import { mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import type { Config, Hooks, PluginInput } from "@opencode-ai/plugin";

type ProviderConfig = NonNullable<Config["provider"]>[string];
type ProviderModel = NonNullable<NonNullable<ProviderConfig["models"]>[string]>;

const GATEWAY_TIMEOUT_MS = 5000;

// models.dev supplies limits, pricing, and modalities the gateway does not report.
const CATALOG_URL = "https://models.dev/api.json";
const CATALOG_TIMEOUT_MS = 10000;
const CATALOG_TTL_MS = 24 * 60 * 60 * 1000;
const CATALOG_VERSION = 2;

// OpenCode disables context compaction when a model reports no context limit,
// so unknown ids inherit one conservative fallback.
const FALLBACK_LIMIT = { context: 200000, output: 32000 };

// Gateway ids may carry a thinking-level qualifier the catalog does not use.
const QUALIFIER_PATTERN = /-(minimal|low|medium|high|max|thinking)$/i;

const INPUT_MODALITIES = ["text", "audio", "image", "video", "pdf"] as const;
type InputModality = (typeof INPUT_MODALITIES)[number];

interface GatewayModelsResponse {
	data?: Array<{ id?: unknown }>;
}

interface CatalogModel {
	name?: string;
	family?: string;
	release_date?: string;
	reasoning?: boolean;
	attachment?: boolean;
	tool_call?: boolean;
	temperature?: boolean;
	limit?: { context?: number; output?: number };
	modalities?: { input?: string[] };
	cost?: { input?: number; output?: number; cache_read?: number; cache_write?: number } | null;
}

interface CatalogCache {
	version: number;
	fetchedAt: number;
	models: Record<string, CatalogModel>;
	suffixes: Record<string, CatalogModel>;
	stripped: Record<string, CatalogModel>;
}

let memoryCatalog: CatalogCache | undefined;

function catalogPath(): string {
	const cacheHome = process.env.XDG_CACHE_HOME ?? join(homedir(), ".cache");
	return join(cacheHome, "agents", "models-dev.json");
}

function widest(current: CatalogModel | undefined, candidate: CatalogModel): CatalogModel {
	if (!current) return candidate;
	return (candidate.limit?.context ?? 0) > (current.limit?.context ?? 0) ? candidate : current;
}

function segment(id: string): string {
	return id.includes("/") ? id.slice(id.lastIndexOf("/") + 1) : id;
}

function stripQualifier(id: string): string {
	return id.replace(QUALIFIER_PATTERN, "");
}

async function readCachedCatalog(): Promise<CatalogCache | undefined> {
	if (memoryCatalog) return memoryCatalog;
	try {
		const parsed = JSON.parse(await readFile(catalogPath(), "utf8")) as CatalogCache;
		if (parsed?.version === CATALOG_VERSION && typeof parsed.fetchedAt === "number" && parsed.models) {
			memoryCatalog = parsed;
		}
	} catch {
		// No usable cache.
	}
	return memoryCatalog;
}

async function loadCatalog(): Promise<CatalogCache | undefined> {
	const cached = await readCachedCatalog();
	if (cached && Date.now() - cached.fetchedAt < CATALOG_TTL_MS) return cached;
	try {
		const response = await fetch(CATALOG_URL, { signal: AbortSignal.timeout(CATALOG_TIMEOUT_MS) });
		if (!response.ok) return cached;
		const providers = (await response.json()) as Record<string, { models?: Record<string, CatalogModel> }>;
		const next: CatalogCache = {
			version: CATALOG_VERSION,
			fetchedAt: Date.now(),
			models: {},
			suffixes: {},
			stripped: {},
		};
		for (const provider of Object.values(providers)) {
			for (const [id, model] of Object.entries(provider.models ?? {})) {
				const suffix = segment(id);
				next.models[id] = widest(next.models[id], model);
				next.suffixes[suffix] = widest(next.suffixes[suffix], model);
				const stripped = stripQualifier(suffix);
				next.stripped[stripped] = widest(next.stripped[stripped], model);
			}
		}
		memoryCatalog = next;
		try {
			await mkdir(dirname(catalogPath()), { recursive: true });
			await writeFile(catalogPath(), JSON.stringify(next));
		} catch {
			// Cache writes are best effort.
		}
		return next;
	} catch {
		return cached;
	}
}

function catalogModel(catalog: CatalogCache | undefined, id: string): CatalogModel | undefined {
	if (!catalog) return undefined;
	return (
		catalog.models[id] ??
		catalog.suffixes[id] ??
		catalog.stripped[stripQualifier(id)] ??
		catalog.stripped[stripQualifier(segment(id))]
	);
}

function inputModalities(entry: CatalogModel | undefined): InputModality[] {
	const values = entry?.modalities?.input ?? ["text"];
	const filtered = values.filter((value): value is InputModality =>
		(INPUT_MODALITIES as readonly string[]).includes(value),
	);
	return filtered.length > 0 ? filtered : ["text"];
}

function toModelConfig(id: string, catalog: CatalogCache | undefined): ProviderModel {
	const entry = catalogModel(catalog, id);
	const input = inputModalities(entry);
	return {
		name: entry?.name ?? id,
		release_date: entry?.release_date ?? "",
		reasoning: entry?.reasoning ?? true,
		attachment: entry?.attachment ?? input.includes("image"),
		tool_call: entry?.tool_call ?? true,
		temperature: entry?.temperature ?? true,
		modalities: { input, output: ["text"] },
		limit: {
			context: entry?.limit?.context ?? FALLBACK_LIMIT.context,
			output: entry?.limit?.output ?? FALLBACK_LIMIT.output,
		},
		cost: {
			input: entry?.cost?.input ?? 0,
			output: entry?.cost?.output ?? 0,
			cache_read: entry?.cost?.cache_read ?? 0,
			cache_write: entry?.cost?.cache_write ?? 0,
		},
	};
}

function gatewayModelIDs(payload: GatewayModelsResponse): string[] {
	return (payload.data ?? [])
		.map((model) => model.id)
		.filter((id): id is string => typeof id === "string" && id.length > 0);
}

const CliproxyDiscoveryPlugin = async (_input: PluginInput): Promise<Hooks> => ({
	config: async (config) => {
		const provider = config.provider?.["cliproxy"];
		const baseURL = provider?.options?.["baseURL"];
		if (!provider || typeof baseURL !== "string") return;
		try {
			const response = await fetch(`${baseURL.replace(/\/+$/, "")}/models`, {
				signal: AbortSignal.timeout(GATEWAY_TIMEOUT_MS),
			});
			if (!response.ok) return;
			const [payload, catalog] = await Promise.all([
				response.json() as Promise<GatewayModelsResponse>,
				loadCatalog(),
			]);
			const models = Object.fromEntries(
				gatewayModelIDs(payload).map((id) => [id, toModelConfig(id, catalog)]),
			);
			if (Object.keys(models).length > 0) provider.models = models;
		} catch {
			// Leave the configured model map untouched when discovery is unavailable.
		}
	},
});

export default {
	id: "cliproxy",
	server: CliproxyDiscoveryPlugin,
};
