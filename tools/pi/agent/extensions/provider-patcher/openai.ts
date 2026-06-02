import { applyServiceTier, type ModelLike, type ServiceTier } from "./logic.js";

type Payload = Record<string, unknown>;

const OPENAI_RESPONSES_APIS = new Set<string>([
  "openai-responses",
  "openai-codex-responses",
]);

const isPayload = (value: unknown): value is Payload =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export const supportsOpenAIServiceTier = (
  model: ModelLike | undefined,
): boolean => !!model && OPENAI_RESPONSES_APIS.has(model.api);

export const effectiveOpenAIServiceTier = (
  model: ModelLike | undefined,
  tier: ServiceTier,
): ServiceTier => {
  if (!supportsOpenAIServiceTier(model)) return "off";
  // Codex's public /fast path maps to OpenAI `priority`; off clears the tier.
  // `flex` 400s on openai-codex-responses, and Codex does not send `default`.
  if (model?.api === "openai-codex-responses" && tier !== "priority")
    return "off";
  return tier;
};

export const supportsOpenAIServiceTierValue = (
  model: ModelLike | undefined,
  tier: ServiceTier,
): boolean => effectiveOpenAIServiceTier(model, tier) === tier;

export const isOpenAIResponsesRequest = (
  model: ModelLike | undefined,
  payload: unknown,
): boolean => {
  if (!model || !isPayload(payload)) return false;
  if (!supportsOpenAIServiceTier(model)) return false;

  // Responses/Codex payloads both use these stable request fields. This avoids
  // baking model IDs or provider names into the policy; custom OpenAI-compatible
  // Responses providers can opt in just by using the Responses API serializer.
  return (
    typeof payload["model"] === "string" &&
    ("input" in payload || "messages" in payload)
  );
};

export const patchOpenAIServiceTier = (
  model: ModelLike | undefined,
  payload: unknown,
  tier: ServiceTier,
): unknown | undefined => {
  if (!isOpenAIResponsesRequest(model, payload)) return undefined;
  return applyServiceTier(payload, effectiveOpenAIServiceTier(model, tier));
};
