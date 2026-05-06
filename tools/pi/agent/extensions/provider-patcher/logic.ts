export type ServiceTier = "off" | "default" | "flex" | "priority";

type Payload = Record<string, unknown>;
export type ModelLike = {
	api: string;
	provider?: string;
	id?: string;
};

const VALID_TIERS = ["off", "default", "flex", "priority"] as const;

const isPayload = (value: unknown): value is Payload => typeof value === "object" && value !== null && !Array.isArray(value);

export const normalizeTier = (value: string | undefined): ServiceTier | undefined => {
	const normalized = value?.trim().toLowerCase();
	if (!normalized) return undefined;
	if (normalized === "normal") return "default";
	if (normalized === "fast") return "priority";
	return VALID_TIERS.includes(normalized as ServiceTier) ? (normalized as ServiceTier) : undefined;
};

export const tierLabel = (tier: ServiceTier): string => {
	switch (tier) {
		case "priority":
			return "priority (fast)";
		case "default":
			return "default (normal)";
		case "flex":
			return "flex (cheap/slower)";
		case "off":
			return "off (do not send service_tier)";
	}
};

export const applyServiceTier = (payload: unknown, tier: ServiceTier): unknown | undefined => {
	if (!isPayload(payload)) return undefined;
	if (tier === "off") {
		if (!("service_tier" in payload)) return undefined;
		const { service_tier: _removed, ...rest } = payload;
		return rest;
	}
	if (payload["service_tier"] === tier) return undefined;
	return { ...payload, service_tier: tier };
};
