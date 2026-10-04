export interface ThinkingLevelMap {
	[key: string]: string | null | undefined;
}

export interface MetadataValue {
	compat?: unknown;
	thinkingLevelMap?: ThinkingLevelMap;
}

export interface BuiltinMetadataEntry {
	provider: string;
	metadata: MetadataValue;
}

/**
 * Resolve builtin request metadata for a gateway id.
 *
 * Gateway ids carry leading pool segments pi's shipped catalog never uses
 * (`command-code/meta/muse-spark-1.3-contributor` vs the catalog's
 * `meta/muse-spark-1.3-contributor`), so match progressively shorter
 * `/`-joined suffixes. When several shipped providers publish the same
 * suffix, the provider named in the gateway id wins.
 */
export function findBuiltinMetadata<TEntry extends BuiltinMetadataEntry>(
	index: Map<string, TEntry[]>,
	id: string,
): TEntry["metadata"] | undefined {
	const parts = id.split("/");
	const providers = new Set(parts);
	for (let start = 0; start < parts.length; start += 1) {
		const candidates = index.get(parts.slice(start).join("/"));
		if (!candidates || candidates.length === 0) continue;
		return (
			candidates.find((candidate) => providers.has(candidate.provider)) ??
			candidates[0]
		).metadata;
	}
	return undefined;
}

export interface ReasoningOption {
	type?: string;
	values?: string[];
}

export interface CatalogModel {
	name?: string;
	reasoning?: boolean;
	reasoning_options?: ReasoningOption[];
	limit?: { context?: number; output?: number };
	modalities?: { input?: string[] };
	cost?: { input?: number; output?: number; cache_read?: number; cache_write?: number } | null;
}

export const STATIC_CATALOG_MODELS: Record<string, CatalogModel> = {
	"devin/swe-2": {
		name: "SWE-2",
		reasoning: true,
		reasoning_options: [{ type: "effort", values: ["medium", "high", "max"] }],
		limit: { context: 262000, output: 64000 },
		modalities: { input: ["text", "image"] },
		cost: { input: 0, output: 0, cache_read: 0, cache_write: 0 },
	},
};

const QUALIFIER_PATTERN = /-(minimal|low|medium|high|xhigh|max|thinking)$/i;

export function stripQualifier(id: string): string {
	return id.replace(QUALIFIER_PATTERN, "");
}

/**
 * Resolve static catalog definitions for known gateway models absent from models.dev.
 *
 * Matches exact id, qualifier-stripped id, and progressively shorter `/`-joined suffixes.
 */
export function findStaticCatalogModel(
	models: Record<string, CatalogModel>,
	id: string,
): CatalogModel | undefined {
	const direct = models[id] ?? models[stripQualifier(id)];
	if (direct) return direct;
	const parts = id.split("/");
	for (let start = 1; start < parts.length; start += 1) {
		const suffix = parts.slice(start).join("/");
		const candidate = models[suffix] ?? models[stripQualifier(suffix)];
		if (candidate) return candidate;
	}
	return undefined;
}
