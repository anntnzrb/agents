import { Model, Plugin, Provider } from "@opencode/plugin";
import type { ProviderRecord } from "@opencode/plugin/promise/provider";

const PROVIDER_ID = Provider.ID.make("cliproxy");
const GATEWAY_TIMEOUT_MS = 5000;
const REFRESH_INTERVAL_MS = 5 * 60 * 1000;

// Gateway ids may carry a thinking-level qualifier the catalog does not use.
const QUALIFIER_PATTERN = /-(minimal|low|medium|high|xhigh|max|thinking)$/i;

// Default effort ladder for the Responses route (matches upstream
// Variant.resolve openaiResponses: none/minimal + low/medium/high + xhigh).
// The cliproxy provider runs @opencode/ai/providers/openai, so variants carry
// Responses-style settings.
const DEFAULT_EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh"] as const;
const EFFORTS: ReadonlySet<string> = new Set([...DEFAULT_EFFORTS, "max"]);

interface GatewayModel {
	id: string;
	ownedBy: string | undefined;
}

interface Catalog {
	exact: Map<string, Model.Info>;
	suffix: Map<string, Model.Info>;
	stripped: Map<string, Model.Info>;
}

function segment(id: string): string {
	return id.includes("/") ? id.slice(id.lastIndexOf("/") + 1) : id;
}

function stripQualifier(id: string): string {
	return id.replace(QUALIFIER_PATTERN, "");
}

function keepWidest(map: Map<string, Model.Info>, key: string, model: Model.Info): void {
	const current = map.get(key);
	if (!current || model.limit.context > current.limit.context) map.set(key, model);
}

// OpenCode's models.dev plugin contributes every catalog provider before this transform runs.
function catalog(records: readonly ProviderRecord[]): Catalog {
	const index: Catalog = { exact: new Map(), suffix: new Map(), stripped: new Map() };
	for (const record of records) {
		if (record.provider.id === PROVIDER_ID) continue;
		for (const [id, model] of record.models) {
			const suffix = segment(id);
			keepWidest(index.exact, id, model);
			keepWidest(index.suffix, suffix, model);
			keepWidest(index.stripped, stripQualifier(suffix), model);
		}
	}
	return index;
}

function lookup(index: Catalog, id: string): Model.Info | undefined {
	return (
		index.exact.get(id) ??
		index.suffix.get(id) ??
		index.stripped.get(stripQualifier(id)) ??
		index.stripped.get(stripQualifier(segment(id)))
	);
}

// Catalog variants are spelled for the source package and mix effort levels with thinking toggles
// and token budgets. An effort variant names its own id in its settings, such as
// reasoningEffort, effort, or thinkingLevel; only those ids carry over to the Responses route.
function isEffort(variant: Model.Info["variants"][number]): boolean {
	if (!EFFORTS.has(variant.id)) return false;
	const settings = JSON.stringify(variant.settings ?? {});
	return settings === "{}" ? variant.id !== "none" : settings.includes(`"${variant.id}"`);
}

function toVariants(entry: Model.Info | undefined): Model.Info["variants"] {
	const efforts = (entry?.variants ?? []).filter(isEffort).map((variant) => variant.id);
	return (efforts.length > 0 ? efforts : DEFAULT_EFFORTS).map((effort) => ({
		id: Model.VariantID.make(effort),
		settings: {
			reasoningEffort: effort,
			reasoningSummary: "auto",
			include: ["reasoning.encrypted_content"],
		},
	}));
}

function toModel(model: GatewayModel, entry: Model.Info | undefined): Model.Info {
	// Multi-segment gateway ids are <pool>/<vendor>/<model>; the pool
	// distinguishes upstreams that vend the same model. Single-segment ids
	// come from OAuth pools, so fall back to the gateway-reported owner.
	const pool = model.id.includes("/") ? model.id.slice(0, model.id.indexOf("/")) : model.ownedBy;
	const name = entry?.name ?? model.id;
	const base = Model.Info.default(PROVIDER_ID, Model.ID.make(model.id));
	return {
		...base,
		name: pool ? `${name} (${pool})` : name,
		time: { released: entry?.time.released ?? 0 },
		capabilities: {
			tools: entry?.capabilities.tools ?? true,
			input: entry ? [...entry.capabilities.input] : ["text"],
			output: ["text"],
		},
		variants: toVariants(entry),
		limit: entry ? { ...entry.limit } : base.limit,
		cost: entry ? structuredClone([...entry.cost]) : base.cost,
	};
}

async function fetchGatewayModels(baseURL: string): Promise<GatewayModel[] | undefined> {
	const response = await fetch(`${baseURL.replace(/\/+$/, "")}/models`, {
		signal: AbortSignal.timeout(GATEWAY_TIMEOUT_MS),
	});
	if (!response.ok) return undefined;
	const payload = (await response.json()) as { data?: Array<{ id?: unknown; owned_by?: unknown }> };
	return (payload.data ?? []).flatMap((model) =>
		typeof model.id === "string" && model.id.length > 0
			? [{ id: model.id, ownedBy: typeof model.owned_by === "string" && model.owned_by ? model.owned_by : undefined }]
			: [],
	);
}

export default Plugin.define({
	id: "cliproxy",
	async setup(ctx) {
		const baseURL = ctx.options.baseURL;
		if (typeof baseURL !== "string") {
			console.warn("cliproxy requires the baseURL plugin option");
			return;
		}
		let inventory: readonly GatewayModel[] = [];
		const refresh = async () => {
			const next = await fetchGatewayModels(baseURL).catch((error: unknown) => {
				console.warn("cliproxy model discovery failed", error);
				return undefined;
			});
			// A failed or empty response keeps the last known inventory.
			if (!next?.length || JSON.stringify(next) === JSON.stringify(inventory)) return false;
			inventory = next;
			return true;
		};

		await refresh();
		await ctx.provider.transform((editor) => {
			if (inventory.length === 0) return;
			const index = catalog(editor.list());
			editor.add({
				info: { ...Provider.Info.empty(PROVIDER_ID), activation: "enabled", settings: { baseURL } },
				models: inventory.map((model) => toModel(model, lookup(index, model.id))),
			});
		});

		const timer = setInterval(() => {
			void refresh()
				.then((changed) => (changed ? ctx.provider.reload() : undefined))
				.catch((error: unknown) => console.warn("cliproxy provider reload failed", error));
		}, REFRESH_INTERVAL_MS);
		return () => clearInterval(timer);
	},
});
