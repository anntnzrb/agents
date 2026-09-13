import { mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { getBuiltinModels, getBuiltinProviders } from "@earendil-works/pi-ai/providers/all";
import type { ExtensionAPI, ProviderModelConfig } from "@earendil-works/pi-coding-agent";
import { findBuiltinMetadata } from "./metadata.js";

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

const THINKING_LEVELS = ["minimal", "low", "medium", "high", "xhigh", "max"] as const;

interface GatewayModelsResponse {
	data?: Array<{ id?: unknown; owned_by?: unknown }>;
}

interface ReasoningOption {
	type?: string;
	values?: string[];
}

interface CatalogModel {
	name?: string;
	reasoning?: boolean;
	reasoning_options?: ReasoningOption[];
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
let builtinIndex: Map<string, BuiltinMetadata[]> | undefined;

type ModelMetadata = Pick<ProviderModelConfig, "compat" | "thinkingLevelMap">;

interface BuiltinMetadata {
	provider: string;
	metadata: ModelMetadata;
}

/**
 * Index pi's shipped catalog by model id. The gateway serves the same upstream models under
 * prefixed ids, so the provider that authored a model also authors its request dialect and
 * thinking-level map; reading that catalog avoids hardcoding request shapes per gateway model.
 * Only `openai-completions` models qualify: this provider speaks that protocol to the gateway, so
 * metadata authored for another protocol describes a request shape this provider never sends.
 */
function builtinMetadataIndex(): Map<string, BuiltinMetadata[]> {
	if (builtinIndex) return builtinIndex;
	const index = new Map<string, BuiltinMetadata[]>();
	const add = (key: string, entry: BuiltinMetadata): void => {
		const entries = index.get(key);
		if (entries) entries.push(entry);
		else index.set(key, [entry]);
	};
	for (const provider of getBuiltinProviders()) {
		for (const model of getBuiltinModels(provider)) {
			if (model.api !== "openai-completions") continue;
			if (!model.compat && !model.thinkingLevelMap) continue;
			const entry = {
				provider,
				metadata: { compat: model.compat, thinkingLevelMap: model.thinkingLevelMap },
			};
			add(model.id, entry);
			add(`${provider}/${model.id}`, entry);
		}
	}
	builtinIndex = index;
	return index;
}

/**
 * Resolve metadata for a gateway id, matching progressively shorter suffixes
 * so leading pool segments (`command-code/...`) resolve to the catalog entry
 * (`meta/...`), with the provider named in the id winning ties.
 */
function builtinMetadata(id: string): ModelMetadata | undefined {
	return findBuiltinMetadata(builtinMetadataIndex(), id);
}

/**
 * Derive thinking-level support from the models.dev effort list, the only effort data available
 * for models pi's shipped catalog does not know yet. Levels a model cannot select stay null so
 * pi clamps to a supported level instead of sending an unsupported one.
 */
function effortLevelMap(options: ReasoningOption[] | undefined): ModelMetadata["thinkingLevelMap"] {
	const values = options?.find((option) => option.type === "effort")?.values;
	if (!values || values.length === 0) return undefined;
	const map: NonNullable<ModelMetadata["thinkingLevelMap"]> = {
		off: values.includes("none") ? "none" : null,
	};
	for (const level of THINKING_LEVELS) map[level] = values.includes(level) ? level : null;
	return map;
}

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

function toModel(id: string, ownedBy: string | undefined, catalog: CatalogCache | undefined): ProviderModelConfig {
	const entry = catalogModel(catalog, id);
	const inputs = entry?.modalities?.input ?? ["text"];
	const metadata = builtinMetadata(id);
	// Multi-segment gateway ids are <pool>/<vendor>/<model>; the pool
	// distinguishes upstreams that vend the same model. Single-segment ids
	// come from OAuth pools, so fall back to the gateway-reported owner.
	const pool = id.includes("/") ? id.slice(0, id.indexOf("/")) : ownedBy;
	const name = entry?.name ?? id;
	return {
		id,
		name: pool ? `${name} (${pool})` : name,
		reasoning: entry?.reasoning ?? true,
		thinkingLevelMap: metadata?.thinkingLevelMap ?? effortLevelMap(entry?.reasoning_options),
		compat: metadata?.compat,
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

function gatewayModels(payload: GatewayModelsResponse): Array<{ id: string; ownedBy?: string }> {
	return (payload.data ?? [])
		.map((model) => ({
			id: model.id,
			ownedBy: typeof model.owned_by === "string" && model.owned_by ? model.owned_by : undefined,
		}))
		.filter((entry): entry is { id: string; ownedBy?: string } => typeof entry.id === "string" && entry.id.length > 0);
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
	return gatewayModels(payload).map((entry) => toModel(entry.id, entry.ownedBy, catalog));
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
