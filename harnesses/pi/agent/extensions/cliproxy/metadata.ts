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
