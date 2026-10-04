import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { typesafeSystemOneApi } from "@earendil-works/pi-ai/api/typesafe-system-one.lazy";
import { getBuiltinClassifierModels, getBuiltinModels, getBuiltinProviders } from "@earendil-works/pi-ai/providers/all";
import type { ExtensionAPI, ExtensionContext, ProviderModelConfig } from "@earendil-works/pi-coding-agent";
import { markTransientStreamError } from "./retry.js";
import {
	findBuiltinMetadata,
	findStaticCatalogModel,
	STATIC_CATALOG_MODELS,
	stripQualifier,
	type CatalogModel,
	type ReasoningOption,
} from "./metadata.js";

// Sync replaces this placeholder with the deployment endpoint.
const BASE_URL = "${CLIPROXY_CLIENT_BASE_URL}";
const GATEWAY_ORIGIN = BASE_URL.replace(/\/+$/, "").replace(/\/v1$/, "");
const GATEWAY_TIMEOUT_MS = 5000;

// models.dev supplies limits, pricing, and modalities the gateway does not report.
const CATALOG_URL = "https://models.dev/api.json";
const CATALOG_TIMEOUT_MS = 10000;
const CATALOG_TTL_MS = 24 * 60 * 60 * 1000;
const MISSING_MODEL_RETRY_MS = 60 * 60 * 1000;
const CATALOG_VERSION = 2;
// Pi asks for the model list as soon as it starts; RPC clients such as Paseo read it before
// discovery can finish. The last discovered catalog is cached so that first read is complete.
const MODELS_CACHE_VERSION = 2;
const MODELS_CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000;
// A model absent from this many consecutive listings is dropped; fewer is a transient gap.
const MISSING_LISTINGS_BEFORE_DROP = 3;

const FALLBACK_CONTEXT_WINDOW = 128000;
const FALLBACK_MAX_TOKENS = 16384;

const THINKING_LEVELS = ["minimal", "low", "medium", "high", "xhigh", "max"] as const;

// Pi's shipped catalog supplies classifier metadata, not gateway availability policy.
const SYSTEM_ONE_UPSTREAM = "openrouter";

interface GatewayModelsResponse {
	data?: Array<{ id?: unknown; owned_by?: unknown; context_length?: unknown; supported_endpoint_types?: unknown }>;
}
interface GatewayModel {
	id: string;
	ownedBy?: string;
	contextLength?: number;
	anthropic: boolean;
}
interface ModelsCache {
	version: number;
	baseUrl: string;
	fetchedAt: number;
	models: ChatModelConfig[];
	missingListings: Record<string, number>;
	fallbackModelIds: string[];
}
interface CatalogCache {
	version: number;
	fetchedAt: number;
	models: Record<string, CatalogModel>;
	suffixes: Record<string, CatalogModel>;
	stripped: Record<string, CatalogModel>;
}
interface ClassifierCache {
	version: number;
	baseUrl: string;
	fetchedAt: number;
	ids: string[];
}

let memoryCatalog: CatalogCache | undefined;
let lastKnown: ChatModelConfig[] = [];
let builtinIndex: Map<string, BuiltinMetadata[]> | undefined;
let lastCatalogAttempt = -Infinity;
let fallbackModels = new Set<string>();
const missingListings = new Map<string, number>();

// Pi does not export the chat or classifier members of the ProviderModelConfig union.
type ChatModelConfig = Extract<ProviderModelConfig, { type?: "chat" }>;
type ClassifierModelConfig = Extract<ProviderModelConfig, { type: "classifier" }>;
type ModelMetadata = Pick<ChatModelConfig, "compat" | "thinkingLevelMap">;

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
	return join(cacheHome, "agents", "models-dev-pi.json");
}

function modelsCachePath(): string {
	const cacheHome = process.env.XDG_CACHE_HOME ?? join(homedir(), ".cache");
	return join(cacheHome, "agents", "cliproxy-models.json");
}

// Pi awaits extension factories. Seed registration before RPC starts serving catalog requests.
async function readModelsCache(): Promise<ChatModelConfig[]> {
	try {
		const parsed = JSON.parse(await readFile(modelsCachePath(), "utf8")) as ModelsCache;
		if (
			parsed?.version !== MODELS_CACHE_VERSION || parsed.baseUrl !== BASE_URL ||
			!Number.isFinite(parsed.fetchedAt) || parsed.fetchedAt > Date.now() ||
			Date.now() - parsed.fetchedAt > MODELS_CACHE_TTL_MS || !Array.isArray(parsed.models) ||
			!parsed.models.every((model) =>
				model && typeof model.id === "string" && model.id.length > 0 &&
				typeof model.name === "string" && model.name.length > 0 &&
				typeof model.reasoning === "boolean" &&
				Array.isArray(model.input) && model.input.length > 0 &&
				model.input.every((input) => input === "text" || input === "image") &&
				model.cost && [model.cost.input, model.cost.output, model.cost.cacheRead, model.cost.cacheWrite]
					.every((cost) => Number.isFinite(cost) && cost >= 0) &&
				Number.isFinite(model.contextWindow) && model.contextWindow > 0 &&
				Number.isFinite(model.maxTokens) && model.maxTokens > 0 &&
				(model.api === undefined || model.api === "anthropic-messages") &&
				(model.api === "anthropic-messages" ? model.baseUrl === GATEWAY_ORIGIN : model.baseUrl === undefined)
			)
		) return [];
		missingListings.clear();
		for (const model of parsed.models) {
			const misses = parsed.missingListings?.[model.id];
			if (Number.isInteger(misses) && misses > 0 && misses < MISSING_LISTINGS_BEFORE_DROP) {
				missingListings.set(model.id, misses);
			}
		}
		const ids = new Set(parsed.models.map((model) => model.id));
		fallbackModels = new Set(
			Array.isArray(parsed.fallbackModelIds) ? parsed.fallbackModelIds.filter((id) => ids.has(id)) : [],
		);
		return parsed.models;
	} catch {
		// No usable cache.
	}
	return [];
}

async function writeModelsCache(models: ChatModelConfig[]): Promise<void> {
	const path = modelsCachePath();
	const temporary = `${path}.${randomUUID()}.tmp`;
	try {
		await mkdir(dirname(path), { recursive: true });
		const cache: ModelsCache = {
			version: MODELS_CACHE_VERSION, baseUrl: BASE_URL, fetchedAt: Date.now(), models,
			missingListings: Object.fromEntries(missingListings),
			fallbackModelIds: [...fallbackModels],
		};
		// Multiple Pi sessions publish here. Readers must never see a partially written catalog.
		await writeFile(temporary, JSON.stringify(cache), { mode: 0o600 });
		await rename(temporary, path);
	} catch {
		// Cache writes are best effort.
	} finally {
		await rm(temporary, { force: true }).catch(() => {});
	}
}

/**
 * Keep models that dropped out of the latest listing until they miss several in a row: a pool
 * that briefly loses an account should not remove a model mid-session.
 */
function retainBrieflyMissing(previous: ChatModelConfig[], current: ChatModelConfig[]): ChatModelConfig[] {
	const listed = new Set(current.map((model) => model.id));
	for (const id of listed) missingListings.delete(id);
	const retained = previous.filter((model) => {
		if (listed.has(model.id)) return false;
		const misses = (missingListings.get(model.id) ?? 0) + 1;
		if (misses >= MISSING_LISTINGS_BEFORE_DROP) {
			missingListings.delete(model.id);
			return false;
		}
		missingListings.set(model.id, misses);
		return true;
	});
	return [...current, ...retained];
}

function widest(current: CatalogModel | undefined, candidate: CatalogModel): CatalogModel {
	if (!current) return candidate;
	return (candidate.limit?.context ?? 0) > (current.limit?.context ?? 0) ? candidate : current;
}

function segment(id: string): string {
	return id.includes("/") ? id.slice(id.lastIndexOf("/") + 1) : id;
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

async function loadCatalog(signal: AbortSignal, force = false): Promise<CatalogCache | undefined> {
	const cached = await readCachedCatalog();
	if (!force && cached && Date.now() - cached.fetchedAt < CATALOG_TTL_MS) return cached;
	if (signal.aborted) return cached;
	lastCatalogAttempt = Date.now();
	try {
		const response = await fetch(CATALOG_URL, {
			signal: AbortSignal.any([signal, AbortSignal.timeout(CATALOG_TIMEOUT_MS)]),
		});
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
		const path = catalogPath();
		const temporary = `${path}.${randomUUID()}.tmp`;
		try {
			await mkdir(dirname(path), { recursive: true });
			await writeFile(temporary, JSON.stringify(next), { mode: 0o600 });
			await rename(temporary, path);
		} catch {
			// Cache writes are best effort.
		} finally {
			await rm(temporary, { force: true }).catch(() => {});
		}
		return next;
	} catch {
		return cached;
	}
}

function catalogModel(catalog: CatalogCache | undefined, id: string): CatalogModel | undefined {
	const staticEntry = findStaticCatalogModel(STATIC_CATALOG_MODELS, id);
	if (staticEntry) return staticEntry;
	if (!catalog) return undefined;
	return (
		catalog.models[id] ??
		catalog.suffixes[id] ??
		catalog.stripped[stripQualifier(id)] ??
		catalog.stripped[stripQualifier(segment(id))]
	);
}

function positiveLimit(value: number | undefined): number | undefined {
	return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : undefined;
}

function toModel(
	{ id, ownedBy, contextLength, anthropic }: GatewayModel,
	catalog: CatalogCache | undefined,
): ChatModelConfig {
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
		contextWindow: positiveLimit(entry?.limit?.context) ?? contextLength ?? FALLBACK_CONTEXT_WINDOW,
		maxTokens: positiveLimit(entry?.limit?.output) ?? FALLBACK_MAX_TOKENS,
		// Claude through Chat Completions loses its thinking text and signatures, which multi-turn
		// reasoning replay needs. The gateway marks the Claude models /v1/messages serves natively;
		// Pi's Anthropic transport appends /v1/messages to the origin itself.
		...(anthropic ? { api: "anthropic-messages", baseUrl: GATEWAY_ORIGIN, compat: undefined } : {}),
	};
}

function gatewayModels(payload: GatewayModelsResponse): GatewayModel[] {
	return (payload.data ?? []).flatMap((model) => {
		if (typeof model.id !== "string" || model.id.length === 0) return [];
		const contextLength = model.context_length;
		const endpoints = model.supported_endpoint_types;
		return [{
			id: model.id,
			ownedBy: typeof model.owned_by === "string" && model.owned_by ? model.owned_by : undefined,
			contextLength: typeof contextLength === "number" && Number.isFinite(contextLength) && contextLength > 0
				? contextLength : undefined,
			anthropic: Array.isArray(endpoints) && endpoints.includes("anthropic"),
		}];
	});
}

async function discover(signal: AbortSignal): Promise<ChatModelConfig[]> {
	const response = await fetch(`${BASE_URL}/models`, {
		signal: AbortSignal.any([signal, AbortSignal.timeout(GATEWAY_TIMEOUT_MS)]),
	});
	if (!response.ok) return [];
	const [payload, catalog] = await Promise.all([
		response.json() as Promise<GatewayModelsResponse>,
		loadCatalog(signal),
	]);
	const gateway = gatewayModels(payload);
	let resolvedCatalog = catalog;
	if (
		gateway.some((entry) => positiveLimit(catalogModel(catalog, entry.id)?.limit?.context) === undefined) &&
		Date.now() - lastCatalogAttempt >= MISSING_MODEL_RETRY_MS
	) {
		resolvedCatalog = await loadCatalog(signal, true);
	}
	for (const entry of gateway) {
		if (positiveLimit(catalogModel(resolvedCatalog, entry.id)?.limit?.context) === undefined && entry.contextLength === undefined) {
			fallbackModels.add(entry.id);
		} else {
			fallbackModels.delete(entry.id);
		}
	}
	return gateway.map((entry) => toModel(entry, resolvedCatalog));
}

/**
 * Classifiers the facade serves, described by pi's catalog entry for the upstream provider. The
 * model inherits the gateway endpoint, and classifiers stay out of `/models` discovery because the
 * gateway does not list them there.
 */
function classifierModels(ids: string[]): ClassifierModelConfig[] {
	const upstream = getBuiltinClassifierModels(SYSTEM_ONE_UPSTREAM);
	return ids.flatMap((id) => {
		const model = upstream.find((entry) => entry.id === id && entry.api === "typesafe-system-one");
		if (!model) return [];
		return [{
			type: "classifier",
			id,
			name: `${model.name} (${SYSTEM_ONE_UPSTREAM})`,
			api: model.api,
			input: model.input,
			cost: model.cost,
			contextWindow: model.contextWindow,
		}];
	});
}

function classifiersCachePath(): string {
	const cacheHome = process.env.XDG_CACHE_HOME ?? join(homedir(), ".cache");
	return join(cacheHome, "agents", "cliproxy-classifiers-pi.json");
}

async function readClassifierCache(): Promise<string[]> {
	try {
		const cache = JSON.parse(await readFile(classifiersCachePath(), "utf8")) as ClassifierCache;
		if (
			cache?.version === 1 && cache.baseUrl === BASE_URL &&
			Number.isFinite(cache.fetchedAt) && cache.fetchedAt <= Date.now() &&
			Date.now() - cache.fetchedAt <= MODELS_CACHE_TTL_MS &&
			Array.isArray(cache.ids) && cache.ids.every((id) => typeof id === "string" && id.length > 0)
		) return cache.ids;
	} catch {
		// No usable cache.
	}
	return [];
}

async function discoverClassifiers(signal: AbortSignal, cached: string[]): Promise<string[]> {
	try {
		const response = await fetch(`${BASE_URL}/systemone/models`, {
			signal: AbortSignal.any([signal, AbortSignal.timeout(GATEWAY_TIMEOUT_MS)]),
		});
		if (!response.ok) return cached;
		const payload = await response.json() as GatewayModelsResponse;
		if (!Array.isArray(payload?.data) || !payload.data.every((model) =>
			model && typeof model.id === "string" && model.id.length > 0
		)) return cached;
		const ids = [...new Set(payload.data.map((model) => model.id as string))];
		if (signal.aborted) return cached;
		const path = classifiersCachePath();
		const temporary = `${path}.${randomUUID()}.tmp`;
		try {
			await mkdir(dirname(path), { recursive: true });
			const cache: ClassifierCache = { version: 1, baseUrl: BASE_URL, fetchedAt: Date.now(), ids };
			await writeFile(temporary, JSON.stringify(cache), { mode: 0o600 });
			await rename(temporary, path);
		} catch {
			// Cache writes are best effort.
		} finally {
			await rm(temporary, { force: true }).catch(() => {});
		}
		return ids;
	} catch {
		return cached;
	}
}

export default async function cliproxy(pi: ExtensionAPI): Promise<void> {
	const warnedModels = new Set<string>();
	const warnFallback = (model: ExtensionContext["model"], ctx: ExtensionContext): void => {
		if (!ctx.hasUI || model?.provider !== "cliproxy" || !fallbackModels.has(model.id) || warnedModels.has(model.id)) return;
		warnedModels.add(model.id);
		ctx.ui.notify(
			`CLIProxyAPI: ${model.id} has no catalog context limit; using the ${FALLBACK_CONTEXT_WINDOW.toLocaleString()}-token fallback.`,
			"warning",
		);
	};
	pi.on("session_start", (_event, ctx) => warnFallback(ctx.model, ctx));
	pi.on("model_select", (event, ctx) => warnFallback(event.model, ctx));
	pi.on("before_agent_start", (_event, ctx) => warnFallback(ctx.model, ctx));
	pi.on("message_end", (event) => {
		if (event.message.role !== "assistant") return;
		const message = markTransientStreamError(event.message);
		return message ? { message } : undefined;
	});

	const staticModels = Object.keys(STATIC_CATALOG_MODELS).map((id) => toModel({ id, anthropic: false }, undefined));
	if (lastKnown.length === 0) lastKnown = await readModelsCache();
	let classifierIds = await readClassifierCache();
	pi.registerProvider("cliproxy", {
		name: "CLIProxyAPI",
		baseUrl: BASE_URL,
		apiKey: "keyless",
		api: "openai-completions",
		models: [...(lastKnown.length > 0 ? lastKnown : staticModels), ...classifierModels(classifierIds)],
		classifiers: { "typesafe-system-one": typesafeSystemOneApi() },
		refreshModels: async (context) => {
			// Pi refreshes in two phases: cache-only at startup (allowNetwork false), then the network.
			if (lastKnown.length === 0) lastKnown = await readModelsCache();
			// The gateway is a LAN endpoint; only explicit offline mode skips discovery.
			if (context.allowNetwork && process.env.PI_OFFLINE === undefined && !context.signal.aborted) {
				classifierIds = await discoverClassifiers(context.signal, classifierIds);
				try {
					const models = await discover(context.signal);
					if (models.length > 0 && !context.signal.aborted) {
						lastKnown = retainBrieflyMissing(lastKnown, models);
						const ids = new Set(lastKnown.map((model) => model.id));
						fallbackModels = new Set([...fallbackModels].filter((id) => ids.has(id)));
						await writeModelsCache(lastKnown);
					}
				} catch {
					// Keep the previous catalog when the gateway is unreachable.
				}
			}
			// The returned list replaces every model, so classifiers ride along with chat discovery.
			return [...(lastKnown.length > 0 ? lastKnown : staticModels), ...classifierModels(classifierIds)];
		},
	});
}
