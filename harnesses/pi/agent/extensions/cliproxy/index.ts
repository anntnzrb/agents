import { mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import type { ExtensionAPI, ProviderModelConfig } from "@earendil-works/pi-coding-agent";

// Sync replaces this placeholder with the deployment endpoint.
const BASE_URL = "${CLIPROXY_CLIENT_BASE_URL}";
const GATEWAY_TIMEOUT_MS = 5000;

// models.dev supplies limits, pricing, and modalities the gateway does not report.
const CATALOG_URL = "https://models.dev/api.json";
const CATALOG_TIMEOUT_MS = 10000;
const CATALOG_TTL_MS = 24 * 60 * 60 * 1000;
const CATALOG_VERSION = 2;

const FALLBACK_CONTEXT_WINDOW = 128000;
const FALLBACK_MAX_TOKENS = 16384;

// Gateway ids may carry a thinking-level qualifier the catalog does not use.
const QUALIFIER_PATTERN = /-(minimal|low|medium|high|max|thinking)$/i;

interface GatewayModelsResponse {
	data?: Array<{ id?: unknown }>;
}

interface CatalogModel {
	name?: string;
	reasoning?: boolean;
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
let lastKnown: ProviderModelConfig[] = [];

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

function toModel(id: string, catalog: CatalogCache | undefined): ProviderModelConfig {
	const entry = catalogModel(catalog, id);
	const inputs = entry?.modalities?.input ?? ["text"];
	return {
		id,
		name: entry?.name ?? id,
		reasoning: entry?.reasoning ?? true,
		input: inputs.includes("image") ? ["text", "image"] : ["text"],
		cost: {
			input: entry?.cost?.input ?? 0,
			output: entry?.cost?.output ?? 0,
			cacheRead: entry?.cost?.cache_read ?? 0,
			cacheWrite: entry?.cost?.cache_write ?? 0,
		},
		contextWindow: entry?.limit?.context ?? FALLBACK_CONTEXT_WINDOW,
		maxTokens: entry?.limit?.output ?? FALLBACK_MAX_TOKENS,
	};
}

function gatewayModelIDs(payload: GatewayModelsResponse): string[] {
	return (payload.data ?? [])
		.map((model) => model.id)
		.filter((id): id is string => typeof id === "string" && id.length > 0);
}

async function discover(signal: AbortSignal): Promise<ProviderModelConfig[]> {
	const response = await fetch(`${BASE_URL}/models`, {
		signal: AbortSignal.any([signal, AbortSignal.timeout(GATEWAY_TIMEOUT_MS)]),
	});
	if (!response.ok) return lastKnown;
	const [payload, catalog] = await Promise.all([
		response.json() as Promise<GatewayModelsResponse>,
		loadCatalog(),
	]);
	return gatewayModelIDs(payload).map((id) => toModel(id, catalog));
}

export default function cliproxy(pi: ExtensionAPI): void {
	pi.registerProvider("cliproxy", {
		name: "CLIProxyAPI",
		baseUrl: BASE_URL,
		apiKey: "keyless",
		api: "openai-completions",
		models: [],
		refreshModels: async (context) => {
			// The gateway is a LAN endpoint; only explicit offline mode skips discovery.
			if (process.env.PI_OFFLINE !== undefined || context.signal.aborted) return lastKnown;
			try {
				const models = await discover(context.signal);
				if (models.length > 0) lastKnown = models;
			} catch {
				// Keep the previous catalog when the gateway is unreachable.
			}
			return lastKnown;
		},
	});
}
