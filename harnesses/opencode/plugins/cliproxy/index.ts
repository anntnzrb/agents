import { mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { Model, Plugin, Provider } from "@opencode/plugin";
import { Money } from "@opencode/schema/money";

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
	data?: Array<{ id?: unknown; owned_by?: unknown }>;
}

interface ReasoningOption {
	type?: string;
	values?: Array<string | null>;
}

interface CatalogModel {
	name?: string;
	family?: string;
	release_date?: string;
	reasoning?: boolean;
	reasoning_options?: ReasoningOption[];
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

// Default effort ladder for the Responses route (matches upstream
// Variant.resolve openaiResponses: none/minimal + low/medium/high + xhigh).
// The cliproxy provider runs aisdk:@ai-sdk/openai, rewritten to
// @opencode/ai/providers/openai, so variants carry Responses-style settings.
const DEFAULT_EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh"] as const;

function effortValues(entry: CatalogModel | undefined): string[] {
	const values = entry?.reasoning_options?.find((option) => option.type === "effort")?.values;
	const seen = new Map<string, true>();
	for (const value of values ?? []) {
		const effort = value ?? "none";
		if (effort.length > 0 && !seen.has(effort)) seen.set(effort, true);
	}
	if (seen.size > 0) return [...seen.keys()];
	return [...DEFAULT_EFFORTS];
}

function toVariants(entry: CatalogModel | undefined): Model.Info["variants"] {
	return effortValues(entry).map((effort) => ({
		id: Model.VariantID.make(effort),
		settings: {
			reasoningEffort: effort,
			reasoningSummary: "auto",
			include: ["reasoning.encrypted_content"],
		},
	}));
}

function toModelConfig(id: string, ownedBy: string | undefined, catalog: CatalogCache | undefined): Model.Info {
	const entry = catalogModel(catalog, id);
	const input = inputModalities(entry);
	// Multi-segment gateway ids are <pool>/<vendor>/<model>; the pool
	// distinguishes upstreams that vend the same model. Single-segment ids
	// come from OAuth pools, so fall back to the gateway-reported owner.
	const pool = id.includes("/") ? id.slice(0, id.indexOf("/")) : ownedBy;
	const name = entry?.name ?? id;
	return {
		...Model.Info.default(Provider.ID.make("cliproxy"), Model.ID.make(id)),
		name: pool ? `${name} (${pool})` : name,
		time: { released: Date.parse(entry?.release_date ?? "") || 0 },
		capabilities: { tools: entry?.tool_call ?? true, input, output: ["text"] },
		variants: toVariants(entry),
		limit: {
			context: entry?.limit?.context ?? FALLBACK_LIMIT.context,
			output: entry?.limit?.output ?? FALLBACK_LIMIT.output,
		},
		cost: [{
			input: Money.USDPerMillionTokens.make(entry?.cost?.input ?? 0),
			output: Money.USDPerMillionTokens.make(entry?.cost?.output ?? 0),
			cache: {
				read: Money.USDPerMillionTokens.make(entry?.cost?.cache_read ?? 0),
				write: Money.USDPerMillionTokens.make(entry?.cost?.cache_write ?? 0),
			},
		}],
	};
}

function gatewayModels(payload: GatewayModelsResponse): Array<{ id: string; ownedBy?: string }> {
	return (payload.data ?? [])
		.map((model) => ({
			id: model.id,
			ownedBy: typeof model.owned_by === "string" && model.owned_by ? model.owned_by : undefined,
		}))
		.filter((entry): entry is { id: string; ownedBy: string | undefined } => typeof entry.id === "string" && entry.id.length > 0);
}

export default Plugin.define({
	id: "cliproxy",
	async setup(ctx) {
		try {
			const baseURL = ctx.options.baseURL;
			if (typeof baseURL !== "string") throw new Error("cliproxy requires the baseURL plugin option");
			const response = await fetch(`${baseURL.replace(/\/+$/, "")}/models`, {
				signal: AbortSignal.timeout(GATEWAY_TIMEOUT_MS),
			});
			if (!response.ok) return;
			const [payload, catalog] = await Promise.all([
				response.json() as Promise<GatewayModelsResponse>,
				loadCatalog(),
			]);
			const models = gatewayModels(payload).map((entry) => toModelConfig(entry.id, entry.ownedBy, catalog));
			if (models.length > 0) {
				await ctx.provider.transform((editor) => {
					editor.add({
						info: {
							...Provider.Info.empty(Provider.ID.make("cliproxy")),
							activation: "enabled",
							settings: { baseURL },
						},
						models,
					});
				});
			}
		} catch (error) {
			console.warn("cliproxy model discovery failed", error);
		}
	},
});
