import { Model, Plugin, Provider } from "@opencode/plugin/effect";
import type { ProviderRecord } from "@opencode/plugin/effect/provider";
import { Effect, Option, Schema } from "effect";

const PROVIDER_ID = Provider.ID.make("cliproxy");
const GATEWAY_TIMEOUT = "5 seconds";
const REFRESH_INTERVAL = "5 minutes";

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

class GatewayError extends Schema.TaggedError<GatewayError>()("cliproxy.GatewayError", {
	message: Schema.String,
	cause: Schema.optional(Schema.Defect()),
}) {}

// Only the envelope is strict; malformed entries are dropped one by one instead of failing the inventory.
const GatewayPayload = Schema.Struct({ data: Schema.optional(Schema.Array(Schema.Unknown)) });
const decodeEntry = Schema.decodeUnknownOption(
	Schema.Struct({ id: Schema.NonEmptyString, owned_by: Schema.optional(Schema.Unknown) }),
);
const decodeNonEmpty = Schema.decodeUnknownOption(Schema.NonEmptyString);

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

const fetchInventory = Effect.fn("cliproxy.fetchInventory")(
	function* (url: string) {
		// One request so the abort signal covers a gateway that stalls after sending headers.
		const body = yield* Effect.tryPromise({
			try: async (signal) => {
				const response = await fetch(url, { signal });
				if (!response.ok) throw new Error(`HTTP ${response.status}`);
				return (await response.json()) as unknown;
			},
			catch: (cause) => new GatewayError({ message: `GET ${url} failed`, cause }),
		});
		const payload = yield* Schema.decodeUnknownEffect(GatewayPayload)(body).pipe(
			Effect.mapError((cause) => new GatewayError({ message: `GET ${url} returned an unexpected payload`, cause })),
		);
		return (payload.data ?? []).flatMap((raw): GatewayModel[] =>
			Option.match(decodeEntry(raw), {
				onNone: () => [],
				onSome: (entry) => [{ id: entry.id, ownedBy: Option.getOrUndefined(decodeNonEmpty(entry.owned_by)) }],
			}),
		);
	},
	Effect.timeout(GATEWAY_TIMEOUT),
);

export default Plugin.define({
	id: "cliproxy",
	effect: Effect.fn("cliproxy")(function* (ctx) {
		const baseURL = Option.getOrUndefined(decodeNonEmpty(ctx.options.baseURL));
		if (baseURL === undefined) return yield* Effect.logWarning("cliproxy requires the baseURL plugin option");
		const url = `${baseURL.replace(/\/+$/, "")}/models`;

		// Written only by the refresh below; read by the synchronous transform on every replay.
		let inventory: readonly GatewayModel[] = [];
		const refresh = Effect.gen(function* () {
			const next = yield* fetchInventory(url);
			// An empty response keeps the last known inventory.
			if (next.length === 0 || JSON.stringify(next) === JSON.stringify(inventory)) return false;
			inventory = next;
			return true;
		}).pipe(
			// A failed refresh keeps the last known inventory.
			Effect.catch((error) => Effect.logWarning("cliproxy model discovery failed", error).pipe(Effect.as(false))),
		);

		yield* refresh;
		yield* ctx.provider.transform((editor) => {
			if (inventory.length === 0) return;
			const index = catalog(editor.list());
			editor.add({
				info: { ...Provider.Info.empty(PROVIDER_ID), activation: "enabled", settings: { baseURL } },
				models: inventory.map((model) => toModel(model, lookup(index, model.id))),
			});
		});

		// The plugin scope interrupts the poller on unload or reload.
		yield* refresh.pipe(
			Effect.flatMap((changed) => (changed ? ctx.provider.reload() : Effect.void)),
			Effect.delay(REFRESH_INTERVAL),
			Effect.forever,
			Effect.forkScoped,
		);
	}),
});
